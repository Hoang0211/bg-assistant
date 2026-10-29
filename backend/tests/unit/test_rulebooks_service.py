from pathlib import Path

from app.services.rulebooks import remove_files


async def test_remove_files_skips_a_file_it_cannot_remove(tmp_path: Path) -> None:
    (tmp_path / "blocked.pdf").mkdir()
    (tmp_path / "ok.pdf").write_bytes(b"x")

    await remove_files(tmp_path, ["blocked.pdf", "ok.pdf"])

    assert list(tmp_path.iterdir()) == [tmp_path / "blocked.pdf"]
