import io
import json
from pathlib import Path

import pytest

from cloud_cost_anomaly.cli import main

EXAMPLE = str(Path(__file__).resolve().parent.parent / "examples" / "daily_costs.csv")


def test_markdown_report_on_example(capsys):
    assert main(["scan", "--export", EXAMPLE, "--days", "30"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Cloud cost anomalies")
    assert "**4 anomalies found**" in out
    assert "| 2025-03-28 | AmazonEC2 | prod |" in out
    assert "`team=data`" in out


def test_json_report_on_example(capsys):
    assert main(["scan", "--export", EXAMPLE, "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["group_by"] == ["service", "account"]
    found = {(a["date"], a["group"]["service"], a["group"]["account"]) for a in data["anomalies"]}
    assert found == {
        ("2025-03-28", "AmazonEC2", "prod"),
        ("2025-04-03", "AmazonS3", "prod"),
        ("2025-04-06", "AmazonCloudWatch", "staging"),
        ("2025-04-07", "AmazonCloudWatch", "staging"),
    }
    top = data["anomalies"][0]["contributors"][0]
    assert top["key"] == {"tag": "team=data"}


def test_short_window_excludes_older_anomalies(capsys):
    main(["scan", "--export", EXAMPLE, "--days", "5", "--format", "json"])
    dates = {a["date"] for a in json.loads(capsys.readouterr().out)["anomalies"]}
    assert dates == {"2025-04-06", "2025-04-07"}


def test_fail_on_anomaly_exit_code(capsys):
    assert main(["scan", "--export", EXAMPLE, "--fail-on-anomaly"]) == 2
    assert main(["scan", "--export", EXAMPLE, "--fail-on-anomaly", "--threshold", "100000"]) == 0
    assert "No anomalies found." in capsys.readouterr().out


def test_reads_stdin(monkeypatch, capsys):
    rows = ["date,service,account,tag,cost"]
    rows += [f"2025-01-{d:02d},EC2,prod,t,100" for d in range(1, 21)]
    rows += ["2025-01-21,EC2,prod,t,500"]
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(rows) + "\n"))
    assert main(["scan", "--export", "-", "--format", "json"]) == 0
    assert len(json.loads(capsys.readouterr().out)["anomalies"]) == 1


def test_output_file(tmp_path, capsys):
    target = tmp_path / "report.md"
    assert main(["scan", "--export", EXAMPLE, "--output", str(target)]) == 0
    assert capsys.readouterr().out == ""
    assert target.read_text().startswith("# Cloud cost anomalies")


@pytest.mark.parametrize(
    "args, message",
    [
        (["--export", "/no/such/file.csv"], "No such file"),
        (["--export", EXAMPLE, "--group-by", "region"], "group-by"),
        (["--export", EXAMPLE, "--days", "0"], "at least 1"),
    ],
)
def test_errors_exit_1_with_message(args, message, capsys):
    assert main(["scan", *args]) == 1
    assert message in capsys.readouterr().err


def test_header_only_file_is_an_error(tmp_path, capsys):
    path = tmp_path / "empty.csv"
    path.write_text("date,service,account,tag,cost\n")
    assert main(["scan", "--export", str(path)]) == 1
    assert "no data rows" in capsys.readouterr().err
