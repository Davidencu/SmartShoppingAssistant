"""
Category-aware retailer selection (migration 011).

A shop is eligible when it's in the right country/tier AND its `category` array
overlaps the requested shop categories, or it is tagged 'general'.
"""
import pytest
from unittest.mock import MagicMock

from services import retailers_service as rs


@pytest.fixture
def ro_retailers(mocker):
    """A small Romanian + global retailer set, injected without touching Supabase."""
    mocker.patch.object(rs, "_ensure_fresh")
    mocker.patch.object(rs, "_domains_by_country", {
        "RO": ["emag.ro", "altex.ro", "notino.ro", "noriel.ro", "pcgarage.ro", "unknown.ro"],
        "GLOBAL": ["amazon.de", "notino.com", "thomann.de"],
    })
    mocker.patch.object(rs, "_niche_domains_by_country", {
        "RO": ["notino.ro", "noriel.ro", "pcgarage.ro"],
        "GLOBAL": ["notino.com", "thomann.de"],
    })
    mocker.patch.object(rs, "_categories_by_domain", {
        "emag.ro": frozenset({"general"}),
        "altex.ro": frozenset({"electronics", "appliances"}),
        "notino.ro": frozenset({"beauty"}),
        "noriel.ro": frozenset({"toys", "baby"}),
        "pcgarage.ro": frozenset({"electronics"}),
        # unknown.ro deliberately missing → treated as 'general'
        "amazon.de": frozenset({"general"}),
        "notino.com": frozenset({"beauty"}),
        "thomann.de": frozenset({"music"}),
    })


class TestNormalizeCategories:
    def test_none_and_empty_mean_no_filter(self):
        assert rs.normalize_categories(None) == frozenset()
        assert rs.normalize_categories([]) == frozenset()

    def test_drops_unknown_values_and_general(self):
        assert rs.normalize_categories(["Appliances", "spaceships", "general"]) == {"appliances"}

    def test_accepts_single_string(self):
        assert rs.normalize_categories("beauty") == {"beauty"}

    def test_matches_sql_constraint_vocabulary(self):
        import pathlib, re
        sql = (pathlib.Path(__file__).parents[3]
               / "supabase/migrations/011_retailer_categories.sql").read_text()
        block = re.search(r"category <@ ARRAY\[(.*?)\]", sql, re.S).group(1)
        sql_values = set(re.findall(r"'([a-z]+)'", block))
        assert sql_values == set(rs.SHOP_CATEGORIES)


class TestCategoryFiltering:
    def test_fridge_excludes_beauty_and_toy_shops(self, ro_retailers):
        niche = rs.get_niche_domains_for_country("RO", ["appliances"])
        assert "notino.ro" not in niche
        assert "noriel.ro" not in niche
        assert niche == []  # no niche appliance shop in this fixture

        local = rs.get_domains_for_country("RO", ["appliances"])
        assert set(local) == {"emag.ro", "altex.ro", "unknown.ro"}

    def test_general_and_unclassified_shops_always_match(self, ro_retailers):
        for cats in (["beauty"], ["music"], ["auto"]):
            local = rs.get_domains_for_country("RO", cats)
            assert "emag.ro" in local
            assert "unknown.ro" in local

    def test_multi_category_overlap(self, ro_retailers):
        assert set(rs.get_niche_domains_for_country("RO", ["baby", "beauty"])) == {
            "notino.ro", "noriel.ro",
        }

    def test_no_categories_returns_everything(self, ro_retailers):
        assert rs.get_niche_domains_for_country("RO") == ["notino.ro", "noriel.ro", "pcgarage.ro"]
        assert rs.get_niche_domains_for_country("RO", []) == ["notino.ro", "noriel.ro", "pcgarage.ro"]

    def test_global_passes_are_filtered_too(self, ro_retailers):
        assert rs.get_global_niche_domains(["music"]) == ["thomann.de"]
        assert rs.get_global_mainstream_domains(["appliances"]) == ["amazon.de"]
        assert set(rs.get_global_domains(["beauty"])) == {"amazon.de", "notino.com"}

    def test_domain_lookup_strips_scheme_and_www(self, ro_retailers):
        assert rs.get_domain_categories("https://www.altex.ro/frigider/p/1") == {
            "electronics", "appliances",
        }
        assert rs.get_domain_categories("never-seen.com") == {"general"}


class TestRefreshWithoutMigration:
    """Before migration 011 is applied the `category` column doesn't exist.
    The service must still load retailers (unfiltered) instead of failing."""

    def test_falls_back_to_old_columns(self, mocker):
        # _refresh() rebinds these module globals; patching restores them afterwards.
        for name in ("_domains_by_country", "_niche_domains_by_country",
                     "_categories_by_domain", "_proxy_domains", "_last_refresh"):
            mocker.patch.object(rs, name, getattr(rs, name))
        old_rows = [{"domain": "emag.ro", "target_country": "RO",
                     "requires_proxy": True, "tier": "mainstream"}]
        table = MagicMock()

        def select(cols):
            q = MagicMock()
            if "category" in cols:
                q.eq.return_value.execute.side_effect = Exception("column category does not exist")
            else:
                q.eq.return_value.execute.return_value.data = old_rows
            return q

        table.select.side_effect = select
        client = MagicMock()
        client.table.return_value = table
        mocker.patch("services.supabase_service.get_supabase_admin", return_value=client)

        rs._refresh()

        assert rs._domains_by_country == {"RO": ["emag.ro"]}
        assert rs._categories_by_domain == {"emag.ro": frozenset({"general"})}
        assert rs.requires_proxy("emag.ro")


class TestPipelineUsesCategories:
    """End-to-end: shop_categories from the intent model restricts Tavily's domains."""

    def test_fridge_search_never_queries_notino(
        self, client, mock_supabase, auth_token, mocker, ro_retailers,
    ):
        from tests.conftest import sse_result

        profile = MagicMock()
        profile.data = {"city": "Bucharest", "country": "Romania"}
        (mock_supabase.table.return_value.select.return_value
         .eq.return_value.single.return_value.execute.return_value) = profile

        mocker.patch("services.gemini_service.classify_intent", return_value={
            "intent": "SEARCH", "reply": None,
            "collected_params": {"category": "Fridge", "budget": "2000 RON",
                                 "budget_max": 2000.0, "budget_currency": "RON",
                                 "preference": "best value for budget"},
            "localized_search_query": "frigider",
            "local_domains": None,
            "shop_categories": ["appliances"],
        })
        mocker.patch("services.gemini_service.generate_embedding", return_value=[0.1] * 768)
        mocker.patch("services.gemini_service.research_community_picks",
                     return_value={"recommendations": [], "insight": None})
        mocker.patch("services.cache_service.lookup_cache", return_value=None)
        mocker.patch("services.gemini_service.explain_no_results", return_value="Nothing found.")
        tavily = mocker.patch("services.tavily_service.search_products", return_value=[])

        resp = client.post(
            "/search/chat",
            json={"messages": [{"role": "user", "content": "frigider sub 2000 lei"}]},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        sse_result(resp)  # pipeline completed

        queried = set()
        for call in tavily.call_args_list:
            domains = call.args[2] if len(call.args) > 2 else call.kwargs.get("include_domains")
            queried.update(domains or [])

        assert tavily.called
        assert "notino.ro" not in queried
        assert "notino.com" not in queried
        assert "noriel.ro" not in queried
        assert {"emag.ro", "altex.ro"} <= queried
