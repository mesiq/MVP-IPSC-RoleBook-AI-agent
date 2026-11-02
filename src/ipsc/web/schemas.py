"""The data the web app returns. The same objects feed the HTML templates and the JSON API."""
from pydantic import BaseModel

from ..answer import Answer
from ..changes import ChangeReport, version_segments


class Citation(BaseModel):
    """One passage exactly as stored in the source PDF."""
    kind: str  # rule | interpretation | manual
    ref: str
    title: str
    text: str
    edition: str
    page: str
    link: str
    note: str = ""
    section: str = ""  # headings the rule sits under (often carry the penalty)


class AnswerOut(BaseModel):
    short_answer: str
    reasoning: str
    certainty: str
    certainty_reason: str
    labels: dict
    language: str
    disciplines: list[str]
    used: list[Citation]
    considered: list[Citation]


class Segment(BaseModel):
    text: str
    marked: bool  # new/changed wording in the newest edition; removed wording in older ones


class ChangeVersion(BaseModel):
    edition: str
    ref: str
    page: str
    link: str
    newest: bool
    segments: list[Segment]


class ChangeOut(BaseModel):
    ref: str
    kind: str  # changed | new | removed
    renumbered: bool
    summary: str = ""
    versions: list[ChangeVersion]


class ChangesOut(BaseModel):
    discipline: str
    topic: str
    editions: list[str]
    notice: str
    total: int
    renumbered: int
    overview: str
    changes: list[ChangeOut]


class SourceOut(BaseModel):
    doc_type: str
    disciplines: list[str]
    edition: str
    pages: int
    chunks: int
    file: str
    link: str


def to_citation(hit) -> Citation:
    return Citation(kind=hit.doc_type, ref=hit.ref, title=hit.title, text=hit.text, edition=hit.edition_label,
                    page=hit.page_label, link=hit.link, note=hit.edition_note,
                    section=hit.context if hit.doc_type == "rule" else "")


def to_answer(answer: Answer, evidence: list) -> AnswerOut:
    return AnswerOut(
        short_answer=answer.short_answer, reasoning=answer.reasoning, certainty=answer.certainty,
        certainty_reason=answer.certainty_reason, labels=answer.labels, language=answer.language,
        disciplines=answer.disciplines,
        used=[to_citation(evidence[n]) for n in answer.used],
        considered=[to_citation(evidence[n]) for n in answer.considered])


def to_changes(report: ChangeReport) -> ChangesOut:
    summaries = {id(change): text for change, text in report.points}
    changes = []
    for change in report.shown:
        versions = [
            ChangeVersion(edition=v.label, ref=v.ref, page=v.page_label, link=v.link,
                          newest=index == len(change.versions) - 1,
                          segments=[Segment(text=t, marked=m) for t, m in version_segments(change, index)])
            for index, v in enumerate(change.versions)]
        changes.append(ChangeOut(ref=change.ref, kind=change.kind, renumbered=change.renumbered,
                                 summary=summaries.get(id(change), ""), versions=versions))
    return ChangesOut(discipline=report.discipline, topic=report.topic, editions=report.editions,
                      notice=report.notice, total=report.total, renumbered=report.renumbered,
                      overview=report.overview, changes=changes)
