"""
Truncated Gemini scoring responses.

Gemini 2.5 Flash can run out of output tokens mid-JSON. The scoring call must
(1) disable thinking so the whole budget goes to the answer, and
(2) salvage every fully-closed product from a cut-off reply before falling back to OpenAI.
"""
import json
from unittest.mock import MagicMock

from services.gemini_service import _salvage_ranked_products, score_and_rank_products


def _product(i: int, title: str) -> dict:
    return {
        "rank": i, "title": title, "url": f"https://altex.ro/frigider-{i}-12345{i}",
        "price": 1999.0 + i, "currency": "RON", "image_url": None,
        "scores": {"cost_efficiency": 80, "quality_confidence": 75, "logistics": 70, "trust": 85},
        "value_score": 0.0, "reasoning": "In stock, under budget {not a brace issue}.",
    }


def _truncated_reply() -> str:
    """Two complete products, then a third cut off inside its title string."""
    full = json.dumps({"ranked_products": [
        _product(1, 'Frigider "Arctic" AK60366M40NFMT'),
        _product(2, "Combina frigorifica Samsung RB34T"),
    ]}, ensure_ascii=False)
    # Drop the closing "]}" and append a partial third object.
    return full[:-2] + ', {"rank": 3, "title": "Combina frigorifica Bosch KGN36, Clasa E, 2 cosu'


class TestSalvage:
    def test_recovers_complete_objects_only(self):
        out = _salvage_ranked_products(_truncated_reply())
        titles = [p["title"] for p in out["ranked_products"]]
        assert titles == ['Frigider "Arctic" AK60366M40NFMT', "Combina frigorifica Samsung RB34T"]

    def test_braces_and_quotes_inside_strings_are_ignored(self):
        out = _salvage_ranked_products(_truncated_reply())
        assert out["ranked_products"][0]["reasoning"] == "In stock, under budget {not a brace issue}."

    def test_cut_inside_first_object_recovers_nothing(self):
        raw = '{"ranked_products": [{"rank": 1, "title": "Lada frigorifica Heinner HCF-287'
        assert _salvage_ranked_products(raw) == {"ranked_products": []}

    def test_missing_key_or_array(self):
        assert _salvage_ranked_products("") == {"ranked_products": []}
        assert _salvage_ranked_products('{"other": 1}') == {"ranked_products": []}
        assert _salvage_ranked_products('{"ranked_products": ') == {"ranked_products": []}


def _scraped():
    return [
        {"url": f"https://altex.ro/frigider-{i}-12345{i}", "title": f"P{i}",
         "markdown": "# Frigider\nPret 2000 lei\nIn stoc."}
        for i in (1, 2, 3)
    ]


def _run(mocker, raw_text: str, openai_return=None):
    resp = MagicMock()
    resp.text = raw_text
    gen = mocker.patch("services.gemini_service._client.models.generate_content", return_value=resp)
    oai = mocker.patch("services.openai_router.score_products", return_value=openai_return or [])
    ranked = score_and_rank_products(_scraped(), "frigider", 2500.0, "RON")
    return ranked, gen, oai


class TestScoringCall:
    def test_thinking_disabled(self, mocker):
        valid = json.dumps({"ranked_products": [_product(1, "A")]})
        _, gen, _ = _run(mocker, valid)
        config = gen.call_args.kwargs["config"]
        assert config.thinking_config is not None
        assert config.thinking_config.thinking_budget == 0

    def test_truncated_reply_is_salvaged_without_openai(self, mocker):
        ranked, _, oai = _run(mocker, _truncated_reply())
        assert len(ranked) == 2
        assert {p["title"] for p in ranked} == {
            'Frigider "Arctic" AK60366M40NFMT', "Combina frigorifica Samsung RB34T",
        }
        oai.assert_not_called()

    def test_nothing_salvageable_falls_back_to_openai(self, mocker):
        raw = '{"ranked_products": [{"rank": 1, "title": "Lada frigorifica Heinner HCF-287'
        ranked, _, oai = _run(mocker, raw, openai_return=[_product(3, "From OpenAI")])
        oai.assert_called_once()
        assert [p["title"] for p in ranked] == ["From OpenAI"]
