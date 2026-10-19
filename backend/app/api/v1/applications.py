"""Protected standalone application packets. Every external application action is manual."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.v1.profile import ProtectedProfileRoute
from backend.app.core.security import require_api_token
from backend.app.db.session import get_db_session
from backend.app.schemas.applications import (
    AnswerEdit,
    ApplicationEventRead,
    CreatePacket,
    Handoff,
    Lifecycle,
    PacketEdit,
    PacketList,
    PacketPreview,
    PacketRead,
    PlatformCapability,
    PrepareInput,
    QuestionsAdd,
    Readiness,
    ReviewInput,
    RevisionInput,
    SubmissionInput,
    SubmissionRead,
    TrackingInput,
)
from backend.app.services.applications.base import ApplicationError
from backend.app.services.applications.review import ApplicationReview
from backend.app.services.applications.service import ApplicationPacketService
from backend.app.services.applications.tracker import ApplicationTracker


class ProtectedApplicationRoute(ProtectedProfileRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe(request):
            try:
                return await handler(request)
            except ApplicationError as exc:
                raise HTTPException(exc.status_code, str(exc)) from exc
            except IntegrityError as exc:
                raise HTTPException(
                    409, "Application data conflict; reload before retrying"
                ) from exc
            except SQLAlchemyError as exc:
                raise HTTPException(503, "Application storage unavailable") from exc

        return safe


router = APIRouter(
    prefix="/api/v1",
    tags=["Application preparation"],
    route_class=ProtectedApplicationRoute,
    dependencies=[Depends(require_api_token)],
)


def application_service(session: AsyncSession = Depends(get_db_session)):
    return ApplicationPacketService(session)


@router.get("/applications/platforms", response_model=list[PlatformCapability])
async def platforms(service: ApplicationPacketService = Depends(application_service)):
    return service.capabilities()


@router.post("/jobs/{job_id}/application-preview", response_model=PacketPreview)
async def preview(
    job_id: UUID,
    data: PrepareInput,
    service: ApplicationPacketService = Depends(application_service),
):
    return await service.preview(job_id, data)


@router.post(
    "/jobs/{job_id}/application-packets", response_model=PacketRead, status_code=201
)
async def create(
    job_id: UUID,
    data: CreatePacket,
    service: ApplicationPacketService = Depends(application_service),
):
    return await service.create(job_id, data)


@router.get("/application-packets", response_model=PacketList)
async def list_packets(
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(25, ge=1, le=100),
    platform: str | None = Query(None, max_length=50),
    job_id: UUID | None = None,
    status: Lifecycle | None = None,
    service: ApplicationPacketService = Depends(application_service),
):
    return await service.list(
        offset=offset, limit=limit, platform=platform, job_id=job_id, status=status
    )


@router.get("/application-packets/{packet_id}", response_model=PacketRead)
async def get_packet(
    packet_id: UUID, service: ApplicationPacketService = Depends(application_service)
):
    return await service.read(packet_id)


@router.patch("/application-packets/{packet_id}", response_model=PacketRead)
async def edit_packet(
    packet_id: UUID,
    data: PacketEdit,
    service: ApplicationPacketService = Depends(application_service),
):
    return await service.edit(packet_id, data)


@router.post("/application-packets/{packet_id}/questions", response_model=PacketRead)
async def add_questions(
    packet_id: UUID,
    data: QuestionsAdd,
    service: ApplicationPacketService = Depends(application_service),
):
    return await service.add_questions(packet_id, data)


@router.post(
    "/application-packets/{packet_id}/questions/{field_id}/generate",
    response_model=PacketRead,
)
async def generate(
    packet_id: UUID,
    field_id: UUID,
    data: RevisionInput,
    service: ApplicationPacketService = Depends(application_service),
):
    return await service.generate(packet_id, field_id, data)


@router.patch(
    "/application-packets/{packet_id}/questions/{field_id}", response_model=PacketRead
)
async def edit_answer(
    packet_id: UUID,
    field_id: UUID,
    data: AnswerEdit,
    service: ApplicationPacketService = Depends(application_service),
):
    return await service.edit_answer(packet_id, field_id, data)


@router.get("/application-packets/{packet_id}/readiness", response_model=Readiness)
async def get_readiness(
    packet_id: UUID, service: ApplicationPacketService = Depends(application_service)
):
    return (await service.read(packet_id)).readiness


@router.post("/application-packets/{packet_id}/review", response_model=PacketRead)
async def review(
    packet_id: UUID,
    data: ReviewInput,
    service: ApplicationPacketService = Depends(application_service),
):
    return await ApplicationReview(service).review(packet_id, data)


@router.get("/application-packets/{packet_id}/handoff", response_model=Handoff)
async def handoff(
    packet_id: UUID, service: ApplicationPacketService = Depends(application_service)
):
    return await ApplicationReview(service).handoff(packet_id)


@router.post(
    "/application-packets/{packet_id}/report-submission", response_model=SubmissionRead
)
async def report_submission(
    packet_id: UUID,
    data: SubmissionInput,
    service: ApplicationPacketService = Depends(application_service),
):
    return await ApplicationTracker(service).report(packet_id, data)


@router.patch("/application-packets/{packet_id}/tracking", response_model=PacketRead)
async def track(
    packet_id: UUID,
    data: TrackingInput,
    service: ApplicationPacketService = Depends(application_service),
):
    return await ApplicationTracker(service).track(packet_id, data)


@router.get(
    "/application-packets/{packet_id}/events", response_model=list[ApplicationEventRead]
)
async def events(
    packet_id: UUID,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(50, ge=1, le=100),
    service: ApplicationPacketService = Depends(application_service),
):
    return await ApplicationTracker(service).events(
        packet_id, offset=offset, limit=limit
    )
