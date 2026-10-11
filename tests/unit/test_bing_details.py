import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ubdict.core.models import Definition, Translation
from ubdict.core.translate.bing import BingAdapter
from ubdict.core.translate.service import _Worker


_BING_HTML = """
<div class="qdef">
  <ul><li><span class="pos">n.</span><span class="def">在场；出席</span></li></ul>
  <div class="hd_div1">复数：<a class="p1-5">presences</a></div>
</div>
<div id="colid"><div class="df_div2">
  <div class="de_title2">adj.+n.</div>
  <div class="col_fl"><a>strong presence</a><a>physical presence</a></div>
</div></div>
<div id="antoid"><div class="df_div2"><div class="col_fl"><a>absence</a></div></div></div>
<div id="authid"><div class="li_sen"><div class="li_pos">
  <span class="pos">n.</span>
  <table>
    <tr class="def_row"><td><div class="de_co"><span class="gra">[u]</span>
      <span class="def_pa"><span class="bil">在场；出席</span>
      <span class="val"><a>the</a><span> </span><a>fact</a><span> </span>
      <a>of</a><span> </span><a>being</a><span> </span><a>in</a><span> </span>
      <a>a</a><span> </span><a>particular</a><span> </span><a>place</a></span></span>
    </div></td></tr>
    <tr class="def_row"><td><div class="li_ex">
      <span class="val_ex"><a>He</a><span> </span><a>hardly</a><span> </span>
      <a>noticed</a><span> </span><a>my</a><span> </span><a>presence</a><span>.</span></span>
      <span class="bil_ex">他似乎没有注意到我在场。</span>
    </div></td></tr>
  </table>
</div></div></div>
"""


def test_bing_parser_extracts_full_dictionary_sections_without_mislabeling():
    definitions = BingAdapter._extract_definitions(_BING_HTML)
    detailed = BingAdapter._extract_detailed_definitions(_BING_HTML)

    assert definitions == [Definition(pos="n.", meaning="在场；出席")]
    assert len(detailed) == 1
    assert detailed[0].pos == "n."
    assert detailed[0].meaning == "在场；出席"
    assert detailed[0].usage == "[u]"
    assert detailed[0].english_meaning == "the fact of being in a particular place"
    assert detailed[0].examples[0].en == "He hardly noticed my presence."
    assert detailed[0].examples[0].zh == "他似乎没有注意到我在场。"
    assert BingAdapter._extract_examples(_BING_HTML) == detailed[0].examples
    assert BingAdapter._extract_word_forms(_BING_HTML) == ["复数：presences"]
    groups = BingAdapter._extract_collocations(_BING_HTML)
    assert groups[0].label == "adj.+n."
    assert groups[0].phrases == ["strong presence", "physical presence"]
    assert BingAdapter._extract_antonyms(_BING_HTML) == ["absence"]


def test_legacy_bing_cache_is_refreshed_and_preserved_on_network_failure():
    cached = Translation.model_validate_json(
        '{"word":"presence","definitions":[{"pos":"n.","meaning":"旧缓存"}],'
        '"source":"bing"}'
    )
    assert not cached.bing_details_loaded

    class Cache:
        def __init__(self):
            self.value = cached
            self.saved = None

        def get(self, _word):
            return self.value

        def set(self, _word, result):
            self.saved = result
            self.value = result

    class Bing:
        name = "bing"

        def __init__(self, result=None, error=None):
            self.result = result
            self.error = error
            self.calls = 0

        async def translate(self, _word):
            self.calls += 1
            if self.error:
                raise self.error
            return self.result

    class Local:
        name = "local"

        def __init__(self):
            self.calls = 0

        async def translate(self, word):
            self.calls += 1
            return Translation(word=word, source="local")

    refreshed = Translation(
        word="presence",
        definitions=[Definition(pos="n.", meaning="在场")],
        detailed_definitions=[Definition(pos="n.", meaning="在场")],
        bing_details_loaded=True,
        source="bing",
    )
    cache = Cache()
    bing = Bing(result=refreshed)
    local = Local()
    worker = _Worker([bing, local], cache, object())

    result = asyncio.run(worker._translate("presence"))
    assert result is refreshed
    assert cache.saved is refreshed
    assert bing.calls == 1
    assert local.calls == 0

    cache = Cache()
    bing = Bing(error=OSError("network unavailable"))
    local = Local()
    worker = _Worker([bing, local], cache, object())

    result = asyncio.run(worker._translate("presence"))
    assert result is cached
    assert bing.calls == 1
    assert local.calls == 0

    incomplete = Translation(
        word="presence",
        definitions=[Definition(pos="n.", meaning="简明释义")],
        source="bing",
    )
    cache = Cache()
    bing = Bing(result=incomplete)
    worker = _Worker([bing, Local()], cache, object())

    result = asyncio.run(worker._translate("presence"))
    assert result is cached
    assert cache.saved is None


def test_bing_result_is_only_marked_complete_when_detailed_senses_parse():
    class Response:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    class Client:
        is_closed = False

        async def get(self, _url):
            return Response(
                '<div class="qdef"><ul><li><span class="pos">n.</span>'
                '<span class="def">meaning</span></li></ul></div>'
            )

    adapter = BingAdapter()
    adapter._client = Client()
    result = asyncio.run(adapter.translate("word"))

    assert result is not None
    assert result.definitions
    assert not result.detailed_definitions
    assert not result.bing_details_loaded


def test_bing_timeout_update_closes_the_previous_async_client():
    class Client:
        is_closed = False

        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True
            self.is_closed = True

    adapter = BingAdapter(timeout=5.0)
    old_client = Client()
    adapter._client = old_client

    asyncio.run(adapter.set_timeout(12.0))

    assert adapter._timeout == 12.0
    assert old_client.closed
    assert adapter._client is None
