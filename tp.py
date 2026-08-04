import asyncio
import os
import traceback
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

root_path = Path(__file__).parent.parent
if str(root_path) not in sys.path:
    sys.path.append(str(root_path))

from livekit.agents import JobContext, Agent, AgentSession, llm, WorkerOptions, cli, UserInputTranscribedEvent, ConversationItemAddedEvent, AutoSubscribe
from livekit.plugins import aws, silero, deepgram
from prompts.interview_agent_prompt import get_system_prompt, get_default_prompt

load_dotenv()

try:
    from .evaluate_gen import evaluate_candidate
except ImportError:
    try:
        from main_live_kit.evaluation_gen import evaluate_candidate
    except ImportError:
        evaluate_candidate = None

try:
    from resume_jd_analyser.db_utils import db_helper
except ImportError:
    try:
        from main_live_kit.resume_jd_analyser.db_utils import db_helper
    except ImportError:
        db_helper = None

async def entrypoint(ctx: JobContext):
    print(f"--- [AGENT] Room {ctx.room.name}: STARTING ---")

    try:
        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    except Exception as e:
        print(f"--- [ERROR] Connection Failed: {e}")
        return

    room_name = ctx.job.room.name if hasattr(ctx, 'job') else ctx.room.name
    interviewer_data = db_helper.get_session(room_name) if db_helper else None

    # Generate system prompt
    if interviewer_data:
        print(f"--- [INFO] Session found: {interviewer_data.get('candidate_name')}")
        system_prompt = get_system_prompt(
            company_name=interviewer_data.get('company_name'),
            job_title=interviewer_data.get('job_title'),
            candidate_name=interviewer_data.get('candidate_name'),
            resume_context=interviewer_data.get('resume_context'),
            questions=interviewer_data.get('questions'),
            jd_data=interviewer_data.get('jd_data')
        )
    else:
        print(f"--- [WARN] No session data for room '{room_name}'. Using default prompt.")
        system_prompt = get_default_prompt()

    chat_ctx = llm.ChatContext()
    chat_ctx.add_message(role="system", content=system_prompt)

    try:
        vad_plugin = silero.VAD.load(min_silence_duration=0.6, min_speech_duration=0.4)

        # ── STT: try local Whisper first, fall back to Deepgram ──────────────
        stt_plugin = None
        try:
            from local_whisper import LocalWhisper
            print("--- [DEBUG] Initializing Local STT (Whisper) ---")
            stt_plugin = LocalWhisper()
            print("--- [DEBUG] Local STT ready. ---")
        except Exception as _stt_err:
            print(f"--- [WARN] Local STT unavailable ({_stt_err}). Falling back to Deepgram STT. ---")
            stt_plugin = deepgram.STT()

        # ── TTS: try local Kokoro first, fall back to Deepgram ───────────────
        tts_plugin = None
        try:
            from kokoro_local import LocalKokoro
            print("--- [DEBUG] Initializing Local TTS (Kokoro) ---")
            tts_plugin = LocalKokoro(
                model_path=model_path,
                voice_path=voice_path,
            )
            print("--- [DEBUG] Local TTS ready. ---")
        except Exception as _tts_err:
            print(f"--- [WARN] Local TTS unavailable ({_tts_err}). Falling back to Deepgram TTS. ---")
            tts_plugin = deepgram.TTS()

        aws_region = (os.environ.get("AWS_REGION") or "ap-south-1").strip("'\"")
        print(f"--- [DEBUG] Initializing LLM: google.gemma-3-12b-it in {aws_region} ---")
        llm_plugin = aws.LLM(model="google.gemma-3-12b-it", region=aws_region)

        session = AgentSession(
            stt=stt_plugin,
            llm=llm_plugin,
            tts=tts_plugin,
            vad=vad_plugin,
        )
    except Exception as e:
        print(f"--- [ERROR] Plugin Init Failed: {e}")
        traceback.print_exc()
        return

    agent = Agent(instructions=system_prompt, chat_ctx=chat_ctx)

    @session.on("user_input_transcribed")
    def on_user_transcript(event: UserInputTranscribedEvent):
        if event.is_final:
            print(f"[TRANSCRIPT] Candidate: {event.transcript}")

    @session.on("conversation_item_added")
    def on_item_added(event: ConversationItemAddedEvent):
        if isinstance(event.item, llm.ChatMessage):
            if event.item.role == "system": return
            role, content = event.item.role, event.item.content 
            print(f"[{role.upper()}] {content}")
            if db_helper:
                try:
                    db_helper.log_message(room_name, "candidate" if role == "user" else "interviewer", str(content))
                except Exception: pass

    await session.start(agent, room=ctx.room)

    name = interviewer_data.get('candidate_name', 'there') if interviewer_data else 'there'
    greeting = f"Hello {name}, I am your AI interviewer today. Let me load your context. Let's begin!"
    try:
        print(f"--- [DEBUG] Agent saying: {greeting}")
        await session.say(greeting, allow_interruptions=False)
        session.generate_reply()
    except Exception as e:
        print(f"--- [ERROR] Initial Speech/Reply Failed: {e}")
        traceback.print_exc()

    print("--- [DEBUG] Agent waiting for room disconnect... ---")
    try:
        await ctx.room.disconnect_future
    except Exception as e:
        print(f"--- [DEBUG] Break in disconnect_future: {e}")
    finally:
        print(f"--- [SHUTDOWN] Room {room_name} disconnected. Starting Evaluation...")
        await run_evaluation(room_name, db_helper)

async def run_evaluation(room_name, db_helper):
    print(f"--- [EVAL] Fetching data for room {room_name}...")
    try:
        if not db_helper: return
        session_data = db_helper.get_session(room_name)
        if not session_data or 'transcript' not in session_data:
            print("--- [ERROR] No transcript found for evaluation.")
            return

        transcript_text = "\n".join([f"{entry.get('role', 'unknown').upper()}: {entry.get('text','')}" for entry in session_data['transcript']])
        jd_text = str(session_data.get('jd_data', 'Not provided'))
        resume_text = str(session_data.get('resume_context', 'Not provided'))

        print("--- [EVAL] Generating evaluation with LLM...")
        if evaluate_candidate:
            eval_json_str = evaluate_candidate(transcript_text, jd_text, resume_text)
            eval_data = json.loads(eval_json_str)
            db_helper.save_evaluation(room_name, eval_data)
            print(f"--- [EVAL] Evaluation saved! Score: {eval_data.get('overall_score')}/10")
        else:
            print("--- [ERROR] evaluate_candidate function not available.")
    except Exception as e:
        print(f"--- [ERROR] Evaluation Failed: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, port=8050))
