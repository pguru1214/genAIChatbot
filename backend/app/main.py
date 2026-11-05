import asyncio
import json
import logging
from contextlib import ExitStack, asynccontextmanager
from threading import Lock
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from langgraph.types import Command
from sqlalchemy.engine import make_url
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import graph
from app.config import get_settings
from app.database import Conversation, Proposal, SessionLocal, Trip, get_db, init_db
from app.conversations import TurnRequest, build_conversation_graph, snapshot
from app.schemas import ChatRequest
from app.errors import public_error
from app.tourism import directory

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    settings = get_settings()
    if settings.app_mode == 'live' and not (settings.gemini_api_key and settings.gemini_model):
        raise RuntimeError('Live mode requires GEMINI_API_KEY and GEMINI_MODEL in backend/.env')
    init_db()
    with ExitStack() as stack:
        url = make_url(settings.database_url)
        if url.get_backend_name() == 'postgresql':
            from langgraph.checkpoint.postgres import PostgresSaver
            connection_url = url.set(drivername='postgresql').render_as_string(hide_password=False)
            saver = stack.enter_context(PostgresSaver.from_conn_string(connection_url))
            saver.setup()
        else:
            from langgraph.checkpoint.sqlite import SqliteSaver
            checkpoint_path = ':memory:' if url.database == ':memory:' else str(url.database) + '.checkpoints'
            saver = stack.enter_context(SqliteSaver.from_conn_string(checkpoint_path))
            saver.setup()
        app.state.conversation_graph = build_conversation_graph(saver)
        app.state.conversation_lock = Lock()
        yield


app = FastAPI(title='TripWeave development API', version='0.1.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins,
                   allow_methods=['GET', 'POST', 'DELETE'], allow_headers=['Content-Type'])


@app.get('/api/health')
def health():
    return {'status': 'ok', 'mode': get_settings().app_mode, 'google_execution': False,
            'authentication': False, 'deployment': 'local-development-only', 'destination_scope': 'India'}


@app.get('/api/tourism/directory')
def tourism_directory():
    """Reviewed sources and explicit coverage, without fetching external pages."""
    return directory()


@app.post('/api/conversations', status_code=201)
def create_conversation(db: Session = Depends(get_db)):
    conversation = Conversation()
    db.add(conversation)
    db.commit()
    return {'id': conversation.id}


@app.get('/api/conversations')
def list_conversations(db: Session = Depends(get_db)):
    return [{'id': c.id, 'title': c.title} for c in db.scalars(
        select(Conversation).order_by(Conversation.created_at.desc()).limit(50))]


@app.get('/api/conversations/{conversation_id}')
def get_conversation(conversation_id: str, db: Session = Depends(get_db)):
    if not db.get(Conversation, conversation_id):
        raise HTTPException(404, 'Conversation not found')
    return snapshot(app.state.conversation_graph, conversation_id)


@app.post('/api/conversations/{conversation_id}/messages')
def conversation_message(conversation_id: str, request: TurnRequest, db: Session = Depends(get_db)):
    if not db.get(Conversation, conversation_id):
        raise HTTPException(404, 'Conversation not found')
    # Local development uses one worker. Serialize runs, including tabs, without
    # holding a SQL transaction during model/provider requests.
    lock = app.state.conversation_lock
    if not lock.acquire(blocking=False):
        raise HTTPException(409, 'A conversation is still running. Wait and reopen it before sending again.')
    workflow = app.state.conversation_graph
    try:
        current = snapshot(workflow, conversation_id)
        if current['checkpoint_id'] != request.checkpoint_id:
            raise HTTPException(409, 'This conversation changed. Reopen it before sending again.')
        if len(current['messages']) >= 100:
            raise HTTPException(422, 'This conversation reached its 100-message limit. Start a new journey.')
        turn = request.model_dump(mode='json', exclude={'checkpoint_id'})
        turn['details'] = request.details.model_dump(mode='json', exclude_none=True)
        graph_input = Command(resume=turn) if current['pending'] else {'turn': turn}
        last_user = next((m['content'] for m in reversed(current['messages']) if m['role'] == 'user'), None)
        unchanged_details = all(current['details'].get(k) == v for k, v in turn['details'].items())
        if current['recoverable'] and request.message in {'Retry saved turn', last_user} and unchanged_details:
            # Resume failed work without appending or charging for another user turn.
            graph_input = None
    except Exception:
        lock.release()
        raise

    def events():
        try:
            run_id = str(uuid4())
            yield sse('progress', {'message': 'Checking your trip details'}, run_id)
            config = {'configurable': {'thread_id': conversation_id}, 'recursion_limit': 12}
            for update in workflow.stream(graph_input, config=config, stream_mode='updates', durability='sync'):
                for node in update:
                    if node != '__interrupt__':
                        yield sse('progress', {'message': {'collect': 'Trip details remembered',
                            'resolve': 'Destination checked', 'plan': 'Preparing your next step', 'save': 'Plan saved', 'clarify': 'Continuing your conversation'}.get(node, node)}, run_id)
                        if node == 'collect' and not update[node].get('question'):
                            yield sse('progress', {'message': 'Researching your destination and building your itinerary'}, run_id)
            view = snapshot(workflow, conversation_id)
            if view['details'].get('destination'):
                with SessionLocal() as session:
                    row = session.get(Conversation, conversation_id)
                    row.title = view['details']['destination']
                    session.commit()
            yield sse('conversation', {'conversation': view}, run_id)
            yield sse('completed', {'conversation_id': conversation_id}, run_id)
        except Exception as error:
            failure = public_error(error)
            logger.warning('Conversation failed: %s category=%s error_type=%s', conversation_id, failure['code'], type(error).__name__)
            if 'saved' not in failure['message'].casefold():
                failure['message'] += ' Your conversation checkpoint is saved.'
            yield sse('error', failure, conversation_id)
        finally:
            lock.release()

    return StreamingResponse(events(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.get('/api/trips')
def trips(db: Session = Depends(get_db)):
    return [{'id': t.id, 'destination': t.destination, 'created_at': t.created_at.isoformat(),
             'answer': t.result['answer'], 'mode': t.result.get('research', {}).get('mode', 'demo')}
            for t in db.scalars(select(Trip).order_by(Trip.created_at.desc()).limit(50))]


@app.get('/api/trips/{trip_id}')
def get_trip(trip_id: str, db: Session = Depends(get_db)):
    trip = db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(404, 'Trip not found')
    return {'id': trip.id, 'destination': trip.destination, 'details': trip.request,
            'result': {**trip.result, 'trip_id': trip.id}}


@app.delete('/api/trips/{trip_id}')
def delete_trip(trip_id: str, db: Session = Depends(get_db)):
    trip = db.get(Trip, trip_id)
    if not trip:
        raise HTTPException(404, 'Trip not found')
    for proposal in db.scalars(select(Proposal).where(Proposal.trip_id == trip_id)):
        db.delete(proposal)
    db.delete(trip)
    db.commit()
    return {'deleted': trip_id}


def sse(kind: str, data: dict, run_id: str) -> str:
    return f'event: {kind}\ndata: {json.dumps({"run_id": run_id, **data})}\n\n'


@app.post('/api/chat')
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    payload = request.model_dump(mode='json')
    if request.intent in {'email', 'calendar'}:
        trip = db.get(Trip, request.trip_id)
        if not trip:
            raise HTTPException(404, 'Saved trip not found')
        payload['saved_answer'] = trip.result['answer']

    async def events():
        run_id = str(uuid4())
        yield sse('progress', {'message': 'Starting LangGraph workflow'}, run_id)
        state = {'request': payload}
        try:
            # The starter streams graph progress, then validated text; not raw model reasoning.
            async with asyncio.timeout(180):
                async for update in graph.astream(state, stream_mode='updates', config={'recursion_limit': 10}):
                    for node, value in update.items():
                        if value:
                            state.update(value)
                        yield sse('progress', {'message': f'{node.capitalize()} completed'}, run_id)
            with SessionLocal() as session:
                if state.get('action'):
                    proposal = Proposal(trip_id=request.trip_id, kind=request.intent,
                                        payload={'content': payload['saved_answer'], **state['action']})
                    session.add(proposal)
                    session.commit()
                    state['proposal_id'] = proposal.id
                    state['trip_id'] = request.trip_id
                else:
                    trip = Trip(destination=request.destination, request=state['request'], result=state)
                    session.add(trip)
                    session.commit()
                    state['trip_id'] = trip.id
            # Chunks are emitted after validation; this is not token-level Gemini streaming.
            for offset in range(0, len(state['answer']), 100):
                yield sse('answer_delta', {'text': state['answer'][offset:offset + 100]}, run_id)
            yield sse('completed', {'result': state}, run_id)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Do not return raw exception strings: provider exceptions can include credentials.
            failure = public_error(error)
            logger.warning('Run failed: %s category=%s', run_id, failure['code'])
            yield sse('error', failure, run_id)

    return StreamingResponse(events(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.post('/api/proposals/{proposal_id}/approve')
def approve(proposal_id: str, db: Session = Depends(get_db)):
    if not db.get(Proposal, proposal_id):
        raise HTTPException(404, 'Proposal not found')
    raise HTTPException(501, 'Google OAuth and live action execution are not implemented. Preview only; nothing was sent or created.')
