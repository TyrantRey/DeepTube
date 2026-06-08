"""Stage 4 (memory) unit tests: record store + ChromaDB semantic round-trip."""

from agent_fyp.models import Segment, Transcript, VideoRecord
from agent_fyp.tools import vectorstore


def test_record_store_roundtrip(sample_record):
    assert vectorstore.get_record(sample_record.video_id) is None

    vectorstore.save_record(sample_record)

    fetched = vectorstore.get_record(sample_record.video_id)
    assert fetched is not None
    assert fetched.title == "Python Basics"
    assert [r.video_id for r in vectorstore.list_records()] == [sample_record.video_id]


def _transcript(texts):
    return Transcript(
        text=" ".join(texts),
        segments=[Segment(start=float(i * 30), text=t) for i, t in enumerate(texts)],
        language="en",
        source="captions",
    )


def test_upsert_and_query_history():
    rec_a = VideoRecord(
        video_id="vid_cooking1",
        url="https://youtu.be/vid_cooking1",
        title="Pasta Recipe",
        video_type="教學",
        summary_md="# Pasta",
    )
    rec_b = VideoRecord(
        video_id="vid_python01",
        url="https://youtu.be/vid_python01",
        title="Python Tutorial",
        video_type="教學",
        summary_md="# Python",
    )

    vectorstore.upsert_history(
        rec_a, _transcript(["How to boil pasta and add tomato sauce for dinner."])
    )
    vectorstore.upsert_history(
        rec_b, _transcript(["Learn Python programming with variables and functions."])
    )

    results = vectorstore.query_history("python programming tutorial", top_k=2)

    assert results
    assert results[0]["video_id"] == "vid_python01"
    assert results[0]["segments"]
    assert "timestamp" in results[0]["segments"][0]


def test_query_history_empty():
    assert vectorstore.query_history("anything") == []


def test_get_transcript_text_roundtrip():
    rec = VideoRecord(
        video_id="vid_txt", youtube_id="yt_txt", url="https://youtu.be/x", title="T"
    )
    vectorstore.upsert_history(rec, _transcript(["Hello there.", "Second part here."]))

    text = vectorstore.get_transcript_text("vid_txt")

    assert "Hello there." in text
    assert "Second part here." in text
    assert "[00:00]" in text  # timestamped lines

    assert vectorstore.get_transcript_text("missing") == ""
