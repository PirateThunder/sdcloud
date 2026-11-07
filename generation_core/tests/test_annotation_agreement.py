import csv

import pytest

from pipeline.evaluation import inter_annotator_agreement


def write_scores(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "annotation_id",
                "generation_status",
                "semantic_score",
                "behavior_score",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def test_no_model_cases_do_not_inflate_expert_agreement(tmp_path):
    rows = [
        {
            "annotation_id": "model",
            "generation_status": "model",
            "semantic_score": "1",
            "behavior_score": "1",
        },
        {
            "annotation_id": "failed",
            "generation_status": "no_model",
            "semantic_score": "0",
            "behavior_score": "0",
        },
    ]
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    write_scores(first, rows)
    write_scores(second, rows)
    result = inter_annotator_agreement(first, second)
    assert result["shared_tasks"] == 2
    assert result["eligible_shared_tasks"] == 1
    assert result["excluded_no_model"] == 1
    assert result["metrics"]["semantic_score"]["pairs"] == 1
    included = inter_annotator_agreement(first, second, include_no_model=True)
    assert included["metrics"]["semantic_score"]["pairs"] == 2


def test_annotation_scores_reject_behavior_semantic_contradiction(tmp_path):
    rows = [
        {
            "annotation_id": "contradiction",
            "generation_status": "model",
            "semantic_score": "0",
            "behavior_score": "1",
        }
    ]
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    write_scores(first, rows)
    write_scores(second, rows)
    with pytest.raises(ValueError, match="requires semantic_score"):
        inter_annotator_agreement(first, second)
