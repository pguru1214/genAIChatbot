import asyncio
import json
import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import graph
from app.config import get_settings
from app.database import Proposal, SessionLocal, Trip, get_db, init_db
from app.schemas import ChatRequest

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    settings = get_settings()
    if settings.app_mode == 'live' and not (settings.gemini_api_key and settings.gemini_model):
        raise RuntimeError('Live mode requires GEMINI_API_KEY and GEMINI_MODEL in backend/.env')
    init_db()
    yield


app = FastAPI(title='TripWeave development API', version='0.1.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins,
                   allow_methods=['GET', 'POST', 'DELETE'], allow_headers=['Content-Type'])


@app.get('/api/health')
def health():
    return {'status': 'ok', 'mode': get_settings().app_mode, 'google_execution': False,
            'authentication': False, 'deployment': 'local-development-only'}


@app.get('/api/trips')
def trips(db: Session = Depends(get_db)):
    return [{'id': t.id, 'destination': t.destination, 'created_at': t.created_at.isoformat(),
             'answer': t.result['answer'], 'mode': t.result.get('research', {}).get('mode', 'demo')}
            for t in db.scalars(select(Trip).order_by(Trip.created_at.desc()).limit(50))]


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
            async with asyncio.timeout(100):
                async for update in graph.astream(state, stream_mode='updates', config={'recursion_limit': 8}):
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
                    trip = Trip(destination=request.destination, request=payload, result=state)
                    session.add(trip)
                    session.commit()
                    state['trip_id'] = trip.id
            # Chunks are emitted after validation; this is not token-level Gemini streaming.
            for offset in range(0, len(state['answer']), 100):
                yield sse('answer_delta', {'text': state['answer'][offset:offset + 100]}, run_id)
            yield sse('completed', {'result': state}, run_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not return raw exception strings: provider exceptions can include credentials.
            logger.warning('Run failed: %s (details withheld to protect provider credentials)', run_id)
            yield sse('error', {'message': 'Unable to complete this request. Check the destination, API access, quotas, and backend configuration.'}, run_id)

    return StreamingResponse(events(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.post('/api/proposals/{proposal_id}/approve')
def approve(proposal_id: str, db: Session = Depends(get_db)):
    if not db.get(Proposal, proposal_id):
        raise HTTPException(404, 'Proposal not found')
    raise HTTPException(501, 'Google OAuth and live action execution are not implemented. Preview only; nothing was sent or created.')
