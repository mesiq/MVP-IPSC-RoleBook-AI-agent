"""The web app. Pages are rendered on the server (Jinja2) and updated in place with HTMX; the same logic is
also available as JSON under /api for other clients.

Run:  ipsc-web   (or: uvicorn ipsc.web.app:app)
"""
import os
import sqlite3
from contextlib import asynccontextmanager, closing
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import answer as answer_module
from .. import changes as changes_module
from .. import config, embed, store
from ..registry import KNOWN_DISCIPLINES
from ..settings import MAX_QUESTION_CHARS
from .limits import JobSlots, RateLimiter
from .schemas import AnswerOut, ChangesOut, SourceOut, to_answer, to_changes

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / "templates")

BUSY = "The service is busy right now. Please try again in a moment."
TOO_MANY = "Too many requests from your address. Please wait a minute."
NEED_DISCIPLINE = "Please choose a discipline (Handgun, PCC, Rifle, Shotgun, Mini Rifle, 22LR Handgun)."


class Problem(Exception):
    """A request that cannot be served; becomes a friendly message in the page or an HTTP error in the API."""

    def __init__(self, message: str, status: int = 400):
        self.message, self.status = message, status


# ---- the work itself (no HTTP in here) -------------------------------------------------------------

def open_db(db_path: Path) -> sqlite3.Connection:
    return store.connect_readonly(db_path)


SCOPES = ("latest", "all")


def answer_question(db_path: Path, question: str, discipline: str) -> AnswerOut | ChangesOut:
    """Answer a question, or - when it asks what changed - compare the rulebook editions."""
    with closing(open_db(db_path)) as con:
        answer, evidence = answer_module.ask(con, question, discipline)
        if answer.intent != "changes":
            return to_answer(answer, evidence)
        if not answer.disciplines:
            raise Problem(NEED_DISCIPLINE)
        report = changes_module.build_report(con, answer.disciplines[0], answer.topic, language=answer.language,
                                                scope=answer.scope)
        return to_changes(report)


def compare_editions(db_path: Path, discipline: str, topic: str, scope: str) -> ChangesOut:
    with closing(open_db(db_path)) as con:
        return to_changes(changes_module.build_report(con, discipline, topic, scope=scope))


def list_sources(db_path: Path) -> list[SourceOut]:
    import json
    order = "ORDER BY tier DESC, doc_type, edition_year DESC, edition_month DESC"
    with closing(open_db(db_path)) as con:
        rows = con.execute(f"SELECT * FROM docs {order}").fetchall()
    return [SourceOut(doc_type=r["doc_type"], disciplines=json.loads(r["disciplines"]), edition=r["edition_label"],
                      pages=r["pages"], chunks=r["n_chunks"], file=r["rel_path"],
                      link=config.source_link(r["path"], r["rel_path"], 1)) for r in rows]


# ---- the app ---------------------------------------------------------------------------------------

def client_id(request: Request) -> str:
    """Who is asking. Behind a reverse proxy (IPSC_TRUST_PROXY=1) use the address it forwards."""
    if os.getenv("IPSC_TRUST_PROXY") == "1":
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def create_app(db_path: Path = config.DB_PATH, data_dir: Path = config.DATA_DIR) -> FastAPI:
    limiter, slots = RateLimiter(), JobSlots()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not db_path.exists():
            raise RuntimeError(f"No database at {db_path}. Run 'ipsc ingest' first.")
        if not config.PUBLIC_URL:
            config.PUBLIC_URL = "/files"  # citations link to the PDFs served by this app
        embed.warm_up()
        yield

    app = FastAPI(title="IPSC Rulebook Assistant", lifespan=lifespan, docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; object-src 'self'; frame-ancestors 'none'; base-uri 'self'")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    def guard(request: Request) -> None:
        """Dependency for the endpoints that cost LLM calls: per-visitor rate limit."""
        if not limiter.allow(client_id(request)):
            raise Problem(TOO_MANY, 429)

    def run_job(work, *args):
        """Run `work` in one of the limited job slots; a busy server answers with a friendly message."""
        if not slots.acquire():
            raise Problem(BUSY, 503)
        try:
            return work(db_path, *args)
        finally:
            slots.release()

    def check_question(question: str) -> str:
        question = question.strip()
        if not question:
            raise Problem("Please type a question.")
        if len(question) > MAX_QUESTION_CHARS:
            raise Problem(f"Please keep the question under {MAX_QUESTION_CHARS} characters.")
        return question

    def check_discipline(discipline: str) -> str:
        if discipline and discipline not in KNOWN_DISCIPLINES:
            raise Problem("Unknown discipline.")
        return discipline

    def page(request: Request, template: str, status: int = 200, **context) -> HTMLResponse:
        """HTMX asks for just the result block; a plain browser request gets the whole page."""
        context.update(disciplines=KNOWN_DISCIPLINES, max_chars=MAX_QUESTION_CHARS)
        if request.headers.get("hx-request"):
            template = "_result.html"
        return templates.TemplateResponse(request, template, context, status_code=status)

    def fail(request: Request, template: str, error: Problem, form: dict) -> HTMLResponse:
        # HTTP 200 on purpose: HTMX only swaps successful responses into the page
        return page(request, template, message=error.message, form=form)

    @app.exception_handler(Problem)
    async def problem_handler(request: Request, error: Problem):
        """Problems raised before a route body runs (rate limit) and all API problems."""
        if request.url.path.startswith("/api/"):
            return JSONResponse(status_code=error.status, content={"detail": error.message})
        template = "changes.html" if request.url.path.startswith("/changes") else "ask.html"
        return fail(request, template, error, {})

    # ---- pages
    @app.get("/", response_class=HTMLResponse)
    def ask_page(request: Request):
        return page(request, "ask.html", form={})

    @app.post("/ask", response_class=HTMLResponse, dependencies=[Depends(guard)])
    def ask_form(request: Request, question: str = Form(""), discipline: str = Form("")):
        form = {"question": question, "discipline": discipline}
        try:
            result = run_job(answer_question, check_question(question), check_discipline(discipline))
        except Problem as error:
            return fail(request, "ask.html", error, form)
        return page(request, "ask.html", result=result, form=form)

    @app.get("/changes", response_class=HTMLResponse)
    def changes_page(request: Request):
        return page(request, "changes.html", form={})

    @app.post("/changes", response_class=HTMLResponse, dependencies=[Depends(guard)])
    def changes_form(request: Request, discipline: str = Form(""), topic: str = Form(""),
                     scope: str = Form("latest")):
        form = {"discipline": discipline, "topic": topic, "scope": scope}
        try:
            if not check_discipline(discipline):
                raise Problem(NEED_DISCIPLINE)
            result = run_job(compare_editions, discipline, topic.strip()[:MAX_QUESTION_CHARS],
                             scope if scope in SCOPES else "latest")
        except Problem as error:
            return fail(request, "changes.html", error, form)
        return page(request, "changes.html", result=result, form=form)

    @app.get("/sources", response_class=HTMLResponse)
    def sources_page(request: Request):
        return templates.TemplateResponse(request, "sources.html", {"sources": list_sources(db_path)})

    @app.get("/files/{rel_path:path}")
    def pdf_file(rel_path: str):
        """The source PDFs, so every citation can be checked. Only PDFs inside the data folder are served."""
        root = data_dir.resolve()
        path = (root / rel_path).resolve()
        if path.suffix.lower() != ".pdf" or not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="application/pdf", content_disposition_type="inline")

    # ---- JSON API
    @app.post("/api/ask", response_model=AnswerOut | ChangesOut, dependencies=[Depends(guard)])
    def api_ask(payload: dict):
        question = check_question(str(payload.get("question", "")))
        discipline = check_discipline(str(payload.get("discipline", "")))
        return run_job(answer_question, question, discipline)

    @app.get("/api/changes", response_model=ChangesOut, dependencies=[Depends(guard)])
    def api_changes(discipline: str, topic: str = "", scope: str = "latest"):
        if not check_discipline(discipline):
            raise Problem(NEED_DISCIPLINE)
        return run_job(compare_editions, discipline, topic.strip()[:MAX_QUESTION_CHARS],
                       scope if scope in SCOPES else "latest")

    @app.get("/api/sources", response_model=list[SourceOut])
    def api_sources():
        return list_sources(db_path)

    @app.get("/api/disciplines")
    def api_disciplines():
        return KNOWN_DISCIPLINES

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()


def main() -> None:
    """Start the server: `ipsc-web` (host and port from IPSC_HOST / IPSC_PORT)."""
    import uvicorn
    uvicorn.run("ipsc.web.app:app", host=os.getenv("IPSC_HOST", "127.0.0.1"), port=int(os.getenv("IPSC_PORT", "8000")),
                proxy_headers=False)
