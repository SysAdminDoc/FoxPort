from foxport.browsers.firefox import import_instructions


def test_forward_import_instructions_cover_all_export_types(tmp_path):
    exports = {
        "passwords": tmp_path / "passwords.csv",
        "hibp": tmp_path / "compromised-passwords.txt",
        "bookmarks": tmp_path / "bookmarks.html",
        "extensions": tmp_path / "extensions.html",
        "cookies": tmp_path / "cookies.sqlite",
        "history": tmp_path / "places.sqlite",
        "autofill": tmp_path / "formhistory.sqlite",
        "cards": tmp_path / "saved-cards.csv",
        "search_engines": tmp_path / "search-engines.json",
        "open_tabs": tmp_path / "recovery.jsonlz4",
        "downloads": tmp_path / "downloads.csv",
    }

    text = import_instructions(None, exports)

    for filename in [
        "passwords.csv",
        "compromised-passwords.txt",
        "bookmarks.html",
        "extensions.html",
        "cookies.sqlite",
        "places.sqlite",
        "formhistory.sqlite",
        "saved-cards.csv",
        "search-engines.json",
        "recovery.jsonlz4",
        "downloads.csv",
    ]:
        assert filename in text
    assert "moving favicons.sqlite to a timestamped backup" in text
    assert "Delete favicons.sqlite" not in text
    assert "plaintext passwords" in text


def test_reverse_import_instructions_use_chrome_workflows(tmp_path):
    text = import_instructions(None, {
        "passwords": tmp_path / "chrome-passwords.csv",
        "bookmarks": tmp_path / "chrome-bookmarks.html",
        "extensions": tmp_path / "chrome-extensions.html",
    })

    assert "Settings -> Autofill and passwords" in text
    assert "Chrome Bookmark Manager" in text
    assert "Chrome Web Store" in text
