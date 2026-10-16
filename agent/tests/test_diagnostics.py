from mro_agent.diagnostics import summarize_pipeline


def test_diagnostics_redacts_sensitive_locations_and_tokens():
    result = summarize_pipeline(
        {
            "pipeline": "pipeline-1",
            "status": "failed",
            "error": "token=abc s3://private-bucket/path/file.zip https://x.example/path?X-Amz-Signature=abc",
        }
    )

    assert result["status"] == "failed"
    assert "abc" not in result["technical_detail"]
    assert "private-bucket" not in result["technical_detail"]
    assert "[REDACTED" in result["technical_detail"]
