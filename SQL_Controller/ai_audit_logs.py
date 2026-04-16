from methods.base.serializer import dumps_json
from methods.infra.database import execute_ai, fetchval_ai


async def create_ai_audit_log(
    request_id: str,
    user_id: int,
    pond_id: int,
    question: str,
    context_summary: dict,
) -> int:
    audit_log_id = await fetchval_ai(
        """
        INSERT INTO ai_audit_logs (
            request_id,
            user_id,
            pond_id,
            question,
            context_summary,
            status
        )
        VALUES ($1, $2, $3, $4, $5::jsonb, 'processing')
        RETURNING id
        """,
        request_id,
        user_id,
        pond_id,
        question,
        dumps_json(context_summary),
    )
    return int(audit_log_id)


async def complete_ai_audit_log(audit_log_id: int, response_text: str) -> None:
    await execute_ai(
        """
        UPDATE ai_audit_logs
        SET
            status = 'completed',
            response_text = $2,
            completed_at = NOW(),
            updated_at = NOW()
        WHERE id = $1
        """,
        audit_log_id,
        response_text,
    )


async def fail_ai_audit_log(audit_log_id: int, error_message: str) -> None:
    await execute_ai(
        """
        UPDATE ai_audit_logs
        SET
            status = 'failed',
            error_message = $2,
            completed_at = NOW(),
            updated_at = NOW()
        WHERE id = $1
        """,
        audit_log_id,
        error_message,
    )
