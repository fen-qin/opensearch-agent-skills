"""Tests that the agent skill is fully standalone — UI and sample data are
bundled inside skills/opensearch-skills/ and resolve without depending on
the repo-root opensearch_orchestrator/ tree."""

import re
import sys
from pathlib import Path

import pytest

_SKILL_ROOT = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills"
_SCRIPTS_DIR = _SKILL_ROOT / "scripts"
_UI_DIR = _SCRIPTS_DIR / "ui"

sys.path.insert(0, str(_SCRIPTS_DIR))


# ---------------------------------------------------------------------------
# UI static assets
# ---------------------------------------------------------------------------
class TestUIAssetsStandalone:
    """Verify the UI files exist inside the skill and that ui.py resolves them."""

    EXPECTED_UI_FILES = ["index.html", "styles.css", "app.jsx"]

    def test_ui_directory_exists(self):
        ui_dir = _SCRIPTS_DIR / "ui"
        assert ui_dir.is_dir(), f"UI directory missing: {ui_dir}"

    @pytest.mark.parametrize("filename", EXPECTED_UI_FILES)
    def test_ui_file_exists(self, filename):
        path = _SCRIPTS_DIR / "ui" / filename
        assert path.is_file(), f"UI file missing: {path}"

    @pytest.mark.parametrize("filename", EXPECTED_UI_FILES)
    def test_ui_file_not_empty(self, filename):
        path = _SCRIPTS_DIR / "ui" / filename
        assert path.stat().st_size > 0, f"UI file is empty: {path}"

    def test_ui_py_resolves_to_local_dir(self):
        from lib.ui import SEARCH_UI_STATIC_DIR

        assert SEARCH_UI_STATIC_DIR.exists(), (
            f"SEARCH_UI_STATIC_DIR does not exist: {SEARCH_UI_STATIC_DIR}"
        )
        # Must point inside the skill, not to opensearch_orchestrator/
        assert "opensearch_orchestrator" not in str(SEARCH_UI_STATIC_DIR), (
            f"SEARCH_UI_STATIC_DIR still points outside the skill: {SEARCH_UI_STATIC_DIR}"
        )

    def test_ui_py_static_dir_contains_all_files(self):
        from lib.ui import SEARCH_UI_STATIC_DIR

        for filename in self.EXPECTED_UI_FILES:
            assert (SEARCH_UI_STATIC_DIR / filename).is_file(), (
                f"SEARCH_UI_STATIC_DIR is missing {filename}"
            )


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------
# The built-in IMDB sample dataset is fetched on demand from IMDb's dataset
# export (https://datasets.imdbws.com/title.basics.tsv.gz) and cached
# locally rather than shipped as a static file. These tests mock the network
# call so they run offline and don't depend on IMDb's live dataset.
_SAMPLE_TSV_BYTES = (
    b"tconst\ttitleType\tprimaryTitle\toriginalTitle\tisAdult\tstartYear\t"
    b"endYear\truntimeMinutes\tgenres\n"
    b"tt0000001\tshort\tCarmencita\tCarmencita\t0\t1894\t\\N\t1\tDocumentary,Short\n"
)


def _make_fake_gzip_response(payload: bytes):
    """Build a gzip-compressed byte string mimicking the IMDb .gz response body."""
    import gzip
    import io

    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(payload)
    return buf.getvalue()


class TestSampleDataStandalone:
    """Verify the IMDB sample dataset is fetched and cached on demand,
    rather than requiring a bundled copy inside the skill."""

    def test_sample_data_not_bundled(self):
        """The skill ships no static sample_data/ directory; sample data
        is fetched at runtime instead."""
        assert not (_SCRIPTS_DIR / "sample_data").exists(), (
            "sample_data/ should not be bundled; samples.py fetches data at runtime"
        )

    def test_load_sample_builtin_imdb_downloads_and_caches(self, monkeypatch, tmp_path):
        import io
        import json

        from lib import samples

        cache_dir = tmp_path / "cache"
        monkeypatch.setattr(samples, "_imdb_cache_dir", lambda: cache_dir)

        gz_bytes = _make_fake_gzip_response(_SAMPLE_TSV_BYTES)

        class _FakeOpener:
            def open(self, req, timeout=None):
                return io.BytesIO(gz_bytes)

        monkeypatch.setattr(samples, "_validate_url", lambda url: None)
        monkeypatch.setattr(samples, "_build_safe_opener", lambda: _FakeOpener())

        result = json.loads(samples.load_sample_builtin_imdb())
        assert "error" not in result, f"load_sample_builtin_imdb failed: {result}"
        assert result["status"] == "loaded"
        assert result["record_count"] > 0

        cached_file = cache_dir / samples._IMDB_SAMPLE_FILENAME
        assert cached_file.is_file(), "Downloaded sample should be cached to disk"

    def test_load_sample_builtin_imdb_uses_cache_without_reopening_network(
        self, monkeypatch, tmp_path
    ):
        """Second call should read from cache and must not hit the network."""
        import json

        from lib import samples

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True)
        cached_file = cache_dir / samples._IMDB_SAMPLE_FILENAME
        cached_file.write_text(_SAMPLE_TSV_BYTES.decode("utf-8"))

        monkeypatch.setattr(samples, "_imdb_cache_dir", lambda: cache_dir)

        def _fail_download(dest):
            raise AssertionError("Should not attempt download when cache exists")

        monkeypatch.setattr(samples, "_download_imdb_sample", _fail_download)

        result = json.loads(samples.load_sample_builtin_imdb())
        assert "error" not in result, f"load_sample_builtin_imdb failed: {result}"
        assert result["status"] == "loaded"

    def test_load_sample_builtin_imdb_surfaces_download_errors(self, monkeypatch, tmp_path):
        import json

        from lib import samples

        cache_dir = tmp_path / "cache"
        monkeypatch.setattr(samples, "_imdb_cache_dir", lambda: cache_dir)

        def _raise(dest):
            raise OSError("network unreachable")

        monkeypatch.setattr(samples, "_download_imdb_sample", _raise)

        result = json.loads(samples.load_sample_builtin_imdb())
        assert "error" in result
        assert "download failed" in result["error"]


# ---------------------------------------------------------------------------
# Simulated install location (mimics .claude/skills/)
# ---------------------------------------------------------------------------
class TestResolvedPathsAreRelative:
    """Ensure path resolution uses only relative traversal from __file__,
    not hardcoded repo-root assumptions."""

    def test_ui_static_dir_is_under_skill_root(self):
        from lib.ui import SEARCH_UI_STATIC_DIR

        resolved = SEARCH_UI_STATIC_DIR.resolve()
        assert str(resolved).startswith(str(_SCRIPTS_DIR)), (
            f"SEARCH_UI_STATIC_DIR escapes the scripts dir: {resolved}"
        )

    def test_samples_imdb_resolution_has_no_repo_root_assumptions(self):
        """Check that load_sample_builtin_imdb's bundled-path fallback and
        cache-dir logic never hardcode a path outside the skill/user cache."""
        import inspect
        from lib.samples import load_sample_builtin_imdb

        source = inspect.getsource(load_sample_builtin_imdb)
        assert "opensearch_orchestrator" not in source, (
            "load_sample_builtin_imdb still references opensearch_orchestrator path"
        )


# ---------------------------------------------------------------------------
# Frontend — agentic fallback warning condition
# ---------------------------------------------------------------------------
_APP_JSX = _UI_DIR / "app.jsx"


@pytest.fixture(scope="module")
def app_jsx_content():
    assert _APP_JSX.exists(), f"app.jsx not found at {_APP_JSX}"
    return _APP_JSX.read_text()


class TestAgenticFallbackWarningCondition:
    def test_fallback_warning_requires_no_dsl_query(self, app_jsx_content):
        """The agentic fallback warning must check !dslQuery so it is hidden
        when the flow agent successfully returns a translated DSL query."""
        lines = app_jsx_content.splitlines()
        fallback_line = None
        for i, line in enumerate(lines):
            if "agentic-fallback-warning" in line or "AI agent unavailable" in line:
                for j in range(max(0, i - 3), i + 1):
                    if "activeTemplate" in lines[j] and "agent" in lines[j]:
                        fallback_line = lines[j]
                        break
                if fallback_line:
                    break

        assert fallback_line is not None, "Could not find agentic fallback warning condition"
        assert "!dslQuery" in fallback_line, (
            "Fallback warning condition must include !dslQuery to hide when "
            "flow agent returns a DSL query"
        )

    def test_fallback_warning_checks_rag_answer(self, app_jsx_content):
        lines = app_jsx_content.splitlines()
        for i, line in enumerate(lines):
            if "agentic-fallback-warning" in line:
                context = "\n".join(lines[max(0, i - 5):i + 1])
                assert "!ragAnswer" in context
                return
        pytest.fail("Could not find agentic-fallback-warning in app.jsx")

    def test_fallback_warning_checks_agent_steps_summary(self, app_jsx_content):
        lines = app_jsx_content.splitlines()
        for i, line in enumerate(lines):
            if "agentic-fallback-warning" in line:
                context = "\n".join(lines[max(0, i - 5):i + 1])
                assert "!agentStepsSummary" in context
                return
        pytest.fail("Could not find agentic-fallback-warning in app.jsx")


# ---------------------------------------------------------------------------
# Frontend — DSL query display
# ---------------------------------------------------------------------------
class TestDslQueryDisplay:
    def test_dsl_query_shown_in_agent_search_results(self, app_jsx_content):
        assert "dslQuery" in app_jsx_content, "dslQuery state variable should exist"
        assert "chat-reasoning-pre" in app_jsx_content, "DSL query should render in a pre block"

    def test_dsl_query_state_initialized(self, app_jsx_content):
        assert 'useState("")' in app_jsx_content or "useState('')" in app_jsx_content


# ---------------------------------------------------------------------------
# Frontend — agentic mode toggle
# ---------------------------------------------------------------------------
class TestAgenticModeToggle:
    def test_agentic_mode_state_exists(self, app_jsx_content):
        assert "agenticMode" in app_jsx_content

    def test_agentic_mode_default_is_search(self, app_jsx_content):
        agentic_mode_lines = [
            line for line in app_jsx_content.splitlines()
            if "agenticMode" in line and "useState" in line
        ]
        assert len(agentic_mode_lines) > 0
        assert any("search" in line for line in agentic_mode_lines)

    def test_chat_mode_available(self, app_jsx_content):
        assert '"chat"' in app_jsx_content or "'chat'" in app_jsx_content


# ---------------------------------------------------------------------------
# Frontend — agent template routing
# ---------------------------------------------------------------------------
class TestAgentTemplateRouting:
    def test_agent_template_triggers_agentic_search(self, app_jsx_content):
        agent_lines = [
            line for line in app_jsx_content.splitlines()
            if 'activeTemplate === "agent"' in line or "activeTemplate === 'agent'" in line
        ]
        assert len(agent_lines) > 0, "UI should check for agent template"

    def test_agent_chat_mode_runs_agent_search(self, app_jsx_content):
        assert "runAgentSearch" in app_jsx_content


# ---------------------------------------------------------------------------
# Frontend — API response field mapping
# ---------------------------------------------------------------------------
class TestApiResponseFieldMapping:
    def test_dsl_query_read_from_response(self, app_jsx_content):
        assert "data.dsl_query" in app_jsx_content or 'data["dsl_query"]' in app_jsx_content

    def test_agentic_agent_type_read_from_schema(self, app_jsx_content):
        assert "agentic_agent_type" in app_jsx_content


# ---------------------------------------------------------------------------
# Frontend — CSS classes
# ---------------------------------------------------------------------------
class TestAgenticCssClasses:
    @pytest.fixture(scope="class")
    def styles_css(self):
        css_path = _UI_DIR / "styles.css"
        assert css_path.exists(), f"styles.css not found at {css_path}"
        return css_path.read_text()

    def test_agentic_fallback_warning_styled(self, styles_css):
        assert ".agentic-fallback-warning" in styles_css

    def test_agentic_mode_toggle_styled(self, styles_css):
        assert ".agentic-mode-toggle" in styles_css

    def test_agentic_mode_btn_styled(self, styles_css):
        assert ".agentic-mode-btn" in styles_css

    def test_agentic_capability_pill_styled(self, styles_css):
        assert ".cap-agentic" in styles_css
