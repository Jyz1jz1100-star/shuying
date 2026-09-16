from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


JobStatus = Literal["queued", "probing", "downloading", "transcribing", "proofreading", "summarizing", "rendering", "completed", "failed", "canceled"]
TranscriptionProfile = Literal["balanced", "accurate"]
LLMProvider = Literal["local", "openai_compatible"]


class StartLiveSubtitlesRequest(BaseModel):
    device_id: int = -1
    transcription_profile: TranscriptionProfile = "balanced"


class CreateJobRequest(BaseModel):
    url: HttpUrl
    transcription_profile: TranscriptionProfile = "balanced"
    llm_provider: LLMProvider = "local"
    processing_mode: Literal['transcript', 'lecture'] = 'lecture'
    transcription_device: Literal['gpu', 'cpu'] = 'gpu'


class UpdateLLMSettingsRequest(BaseModel):
    default_provider: LLMProvider = "local"
    api_base_url: str = Field(default="https://api.openai.com/v1", max_length=500)
    api_model: str = Field(default="", max_length=200)
    api_key: str | None = Field(default=None, max_length=1000)
    local_model: str | None = Field(default=None, min_length=1, max_length=200)


class TestLLMSettingsRequest(BaseModel):
    api_base_url: str = Field(min_length=1, max_length=500)
    api_model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=1000)


class TimelineItem(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    heading: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=1200)


class KeyPoint(BaseModel):
    point: str = Field(min_length=1, max_length=1200)
    timestamps: list[float] = Field(default_factory=list)


class ActionItem(BaseModel):
    action: str = Field(min_length=1, max_length=600)
    timestamp: float | None = Field(default=None, ge=0)


class TermDefinition(BaseModel):
    term: str = Field(min_length=1, max_length=100)
    definition: str = Field(min_length=1, max_length=600)


class SourceMetadata(BaseModel):
    video_title: str
    platform: str
    author: str = "未知"
    duration_seconds: float = Field(ge=0)
    source_url: str
    transcript_language: str = "unknown"
    transcription_method: str = "unknown"
    llm_model: str = "未记录"


class VideoSummary(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    one_sentence_summary: str = Field(min_length=1, max_length=500)
    overview: str = Field(min_length=1, max_length=4000)
    timeline: list[TimelineItem] = Field(default_factory=list)
    key_points: list[KeyPoint] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    terms: list[TermDefinition] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    source: SourceMetadata


class ChunkSummary(BaseModel):
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    synopsis: str = Field(min_length=1, max_length=2500)
    key_points: list[KeyPoint] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    terms: list[TermDefinition] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class ArticleSection(BaseModel):
    heading: str = Field(min_length=1, max_length=160)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    paragraphs: list[str] = Field(min_length=1, max_length=20)


class ArticleDocument(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    lead: str = Field(min_length=1, max_length=4000)
    sections: list[ArticleSection] = Field(min_length=1)
    source: SourceMetadata


class ProofreadSegment(BaseModel):
    index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=3000)


class ProofreadBatch(BaseModel):
    segments: list[ProofreadSegment] = Field(min_length=1)


class TranscriptSegment(BaseModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(ge=0, allow_inf_nan=False)
    text: str = Field(min_length=1)

    @model_validator(mode='after')
    def ordered_times(self):
        if self.end < self.start:
            raise ValueError('字幕结束时间不能早于开始时间')
        return self


class Transcript(BaseModel):
    language: str
    source: Literal["human_subtitles", "whisper", "whisper_cpp", "unknown"]
    segments: list[TranscriptSegment]
    proofread_by: str | None = None
