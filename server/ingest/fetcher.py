import random
import time

import httpx

from server.common.logging import get_logger
from server.ingest.models import CompaniesFile
from server.ingest.registry import (
    already_have,
    latest_attempt_outcome,
    record_attempt,
    register,
)
from server.ingest.sources.base import SourceAdapter

logger = get_logger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
CIRCUIT_BREAKER_THRESHOLD = 5


class PoliteClient:
    """Rate-limited HTTP client with retry+backoff, for automated fetching.

    Waits at least `delay` seconds between requests (regardless of host), retries
    retryable failures with exponential backoff and jitter, and identifies itself
    with a descriptive User-Agent, per the phase doc's "polite scraping" rules.
    """

    def __init__(
        self,
        user_agent: str,
        delay: float,
        timeout: float,
        max_retries: int,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )
        self.delay = delay
        self.max_retries = max_retries
        self._last_request_at = 0.0

    def get(self, url: str) -> httpx.Response:
        wait = self.delay - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)

        backoff = 2.0
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.get(url)
                self._last_request_at = time.monotonic()
                if response.status_code in RETRYABLE_STATUS:
                    raise httpx.HTTPStatusError(
                        f"retryable status {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                return response
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                last_error = e
                self._last_request_at = time.monotonic()
                if attempt == self.max_retries:
                    raise
                time.sleep(backoff + random.uniform(0, 1))
                backoff *= 2
        raise last_error or RuntimeError("unreachable")  # satisfies the type checker

    def close(self) -> None:
        self.client.close()


def fetch_all(
    companies_file: CompaniesFile,
    adapters: list[SourceAdapter],
    client: PoliteClient,
) -> None:
    """Runs every adapter against every configured company/fiscal-year target,
    skipping documents already registered and recording every attempt (ok,
    duplicate, manual_needed, resolve_failed, or failed) to `fetch_attempts`.

    Circuit breaker: an adapter stops (moving on to the next one) after 5
    consecutive request failures, rather than continuing to hammer a host that
    is clearly down or blocking us.
    """
    for company in companies_file.companies:
        for adapter in adapters:
            consecutive_failures = 0
            for target in adapter.targets(company, companies_file.fiscal_years):
                if already_have(target.company_id, target.doc_type, target.fiscal_year):
                    continue

                try:
                    urls = adapter.resolve_urls(client, target)
                except Exception as e:
                    record_attempt(
                        company_id=target.company_id,
                        doc_type=target.doc_type,
                        fiscal_year=target.fiscal_year,
                        url=None,
                        http_status=None,
                        outcome="resolve_failed",
                        error=str(e),
                    )
                    continue

                if not urls:
                    # Rerunning `hl fetch` must not pile up one identical
                    # manual_needed row per target per run.
                    if (
                        latest_attempt_outcome(
                            target.company_id, target.doc_type, target.fiscal_year
                        )
                        == "manual_needed"
                    ):
                        continue
                    record_attempt(
                        company_id=target.company_id,
                        doc_type=target.doc_type,
                        fiscal_year=target.fiscal_year,
                        url=None,
                        http_status=None,
                        outcome="manual_needed",
                        error=None,
                    )
                    continue

                for url in urls:
                    if consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
                        logger.warning(
                            f"{adapter.name}: {consecutive_failures} consecutive failures, "
                            "stopping this adapter for this company"
                        )
                        break
                    try:
                        response = client.get(url)
                        doc_id, created = register(
                            response.content,
                            company_id=target.company_id,
                            doc_type=target.doc_type,
                            fiscal_year=target.fiscal_year,
                            source_url=url,
                        )
                        record_attempt(
                            company_id=target.company_id,
                            doc_type=target.doc_type,
                            fiscal_year=target.fiscal_year,
                            url=url,
                            http_status=response.status_code,
                            outcome="ok" if created else "duplicate",
                            error=None,
                        )
                        consecutive_failures = 0
                    except Exception as e:
                        record_attempt(
                            company_id=target.company_id,
                            doc_type=target.doc_type,
                            fiscal_year=target.fiscal_year,
                            url=url,
                            http_status=None,
                            outcome="failed",
                            error=str(e),
                        )
                        consecutive_failures += 1
