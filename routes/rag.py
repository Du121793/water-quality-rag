import uuid

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, Request, UploadFile, status

from SQL_Controller.paper_chunks import count_paper_chunks
from SQL_Controller.rag_ingest_jobs import create_rag_ingest_job, get_rag_ingest_job
from methods.ai.auth import resolve_web_user_id
from methods.base.logger import info
from methods.base.schemas import RebuildEmbeddingsRequest
from methods.rag.embeddings import embedding_is_configured, get_embedding_identity
from methods.rag.paper_rag_service import check_duplicate_by_pdf, ingest_pdf_file, list_papers_for_api
from methods.rag.rag_ingest_background import run_rag_embedding_job, run_rag_embedding_rebuild_job

router = APIRouter()


@router.get("/papers")
async def list_papers():
    return {
        "success": True,
        "data": await list_papers_for_api(),
    }


@router.get("/ingest-jobs/{job_id}")
async def get_ingest_job(
    job_id: str,
    request: Request,
    user_id: int | None = Query(default=None),
):
    resolved_user_id = await resolve_web_user_id(request, user_id)
    job = await get_rag_ingest_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到指定的匯入任務。")

    requested_by = job.get("requested_by")
    if requested_by is not None and int(requested_by) != resolved_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你沒有權限查看此匯入任務。")

    return {
        "success": True,
        "data": job,
    }


@router.post("/papers/check-duplicate")
async def check_duplicate_paper(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(...),
    source_url: str | None = Form(default=None),
    doi: str | None = Form(default=None),
    operator_user_id: int | None = Form(default=None),
):
    user_id = await resolve_web_user_id(request, operator_user_id)
    pdf_bytes = await file.read()

    info("RAG匯入", f"開始檢查重複文章 user_id={user_id} filename={file.filename}", request.client.host if request.client else "")

    result = await check_duplicate_by_pdf(
        title=title,
        source_url=source_url,
        doi=doi,
        pdf_bytes=pdf_bytes,
    )
    return {
        "success": True,
        "data": result,
    }


@router.post("/papers")
async def upload_paper(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(...),
    source_url: str | None = Form(default=None),
    doi: str | None = Form(default=None),
    authors: str | None = Form(default=None),
    journal_name: str | None = Form(default=None),
    published_at: str | None = Form(default=None),
    duplicate_policy: str = Form(default="reject"),
    operator_user_id: int | None = Form(default=None),
):
    user_id = await resolve_web_user_id(request, operator_user_id)
    info("RAG匯入", f"開始接收論文 user_id={user_id} filename={file.filename}", request.client.host if request.client else "")

    result = await ingest_pdf_file(
        title=title,
        upload_file=file,
        source_url=source_url,
        doi=doi,
        authors=authors,
        journal_name=journal_name,
        published_at=published_at,
        duplicate_policy=duplicate_policy,
        run_embedding=False,
    )

    inserted_chunks = result.pop("inserted_chunks", [])
    if inserted_chunks and embedding_is_configured():
        embedding_provider, embedding_model = get_embedding_identity()
        job_id = str(uuid.uuid4())
        await create_rag_ingest_job(
            job_id=job_id,
            paper_source_id=int(result["paper_source"]["id"]) if result.get("paper_source") else None,
            requested_by=user_id,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            chunk_total=len(inserted_chunks),
        )
        background_tasks.add_task(run_rag_embedding_job, job_id, inserted_chunks)
        result["embedding_job_id"] = job_id
        result["embedding_status"] = "queued"
    else:
        result["embedding_job_id"] = None
        result["embedding_status"] = "skipped" if not inserted_chunks else "disabled"

    return {
        "success": True,
        "data": result,
    }


@router.post("/embeddings/rebuild-all")
async def rebuild_all_embeddings(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: RebuildEmbeddingsRequest,
):
    user_id = await resolve_web_user_id(request, payload.user_id)

    if not embedding_is_configured():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="目前未設定 embedding 模型。")

    chunk_total = await count_paper_chunks()
    embedding_provider, embedding_model = get_embedding_identity()
    job_id = str(uuid.uuid4())

    await create_rag_ingest_job(
        job_id=job_id,
        paper_source_id=None,
        requested_by=user_id,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        chunk_total=chunk_total,
    )

    background_tasks.add_task(
        run_rag_embedding_rebuild_job,
        job_id,
        payload.purge_current_model_embeddings,
        payload.purge_other_model_embeddings,
    )

    info(
        "RAG重建",
        (
            f"已建立整庫向量重建任務 job_id={job_id} user_id={user_id} "
            f"provider={embedding_provider} model={embedding_model} chunk_total={chunk_total}"
        ),
        request.client.host if request.client else "",
    )

    return {
        "success": True,
        "data": {
            "job_id": job_id,
            "status": "queued",
            "chunk_total": chunk_total,
            "embedding_provider": embedding_provider,
            "embedding_model": embedding_model,
            "purge_current_model_embeddings": payload.purge_current_model_embeddings,
            "purge_other_model_embeddings": payload.purge_other_model_embeddings,
        },
    }
