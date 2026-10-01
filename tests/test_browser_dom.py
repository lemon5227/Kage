"""Real Chromium actions and backend saved state, not dictionary-only contracts."""
import asyncio
import json

import pytest

pytest.importorskip('playwright.async_api', reason='optional computer-use dependency')
from playwright.async_api import async_playwright


@pytest.fixture
def profile_server():
    from scripts.experiments.browser_fixture import profile_server as server
    with server() as value:
        yield value


def target(obs,label):
    return next(row['target_ref'] for row in obs['targets'] if row['label']==label)


def test_real_tools_fill_save_wait_and_read_backend(profile_server,tmp_path):
    async def run():
        from core.computer_use.browser import BrowserAdapter
        from core.tool_registry import ToolRegistry
        from core.tool_executor import ToolExecutor
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True)
            try:
                page=await browser.new_page(); adapter=BrowserAdapter(page,trace_path=tmp_path/'browser.jsonl')
                registry=ToolRegistry();adapter.register_tools(registry)
                tools=ToolExecutor(registry,str(tmp_path))
                result=await tools.execute('browser_open',{'url':profile_server[0]})
                assert result.success
                obs=json.loads(result.result)['observation']
                filled=await tools.execute('browser_act',{'observation_id':obs['observation_id'],'operation':'fill','target_ref':target(obs,'Name'),'value':'Wenbo 实验'})
                obs=json.loads(filled.result)['observation']
                saved=await tools.execute('browser_act',{'observation_id':obs['observation_id'],'operation':'click','target_ref':target(obs,'Save profile')})
                obs=json.loads(saved.result)['observation']
                waited=await tools.execute('browser_act',{'observation_id':obs['observation_id'],'operation':'wait','value':'Saved: Wenbo 实验'})
                assert waited.success and 'Saved: Wenbo 实验' in json.loads(waited.result)['observation']['text']
                assert await (await page.request.get(profile_server[0]+'/record')).json()=={'name':'Wenbo 实验'}
                assert profile_server[1]['posts']==1
                rows=[json.loads(line) for line in (tmp_path/'browser.jsonl').read_text().splitlines()]
                assert {r['phase'] for r in rows} >= {'open','observe','execute','wait'}
                assert all(r['elapsed_ms']>=0 for r in rows)
            finally: await browser.close()
    asyncio.run(run())


def test_replaced_identical_button_and_moved_target_require_reobservation(profile_server):
    async def run():
        from core.computer_use.browser import BrowserAdapter
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True)
            try:
                page=await browser.new_page();adapter=BrowserAdapter(page)
                obs=(await adapter.open(profile_server[0]))['observation']
                ref=target(obs,'Save profile')
                await page.evaluate("document.querySelector('button').replaceWith(document.querySelector('button').cloneNode(true))")
                result=await adapter.act(obs['observation_id'],'click',ref)
                assert result['error']=='StaleObservation' and result['outcome']=='rejected'
                assert profile_server[1]['posts']==0
                fresh=result['observation']
                assert target(fresh,'Save profile')!=ref
                await page.evaluate("document.querySelector('button').style.marginLeft='100px'")
                result=await adapter.act(fresh['observation_id'],'click',target(fresh,'Save profile'))
                assert result['error']=='StaleObservation' and profile_server[1]['posts']==0
            finally: await browser.close()
    asyncio.run(run())


def test_scroll_timeout_and_old_observation_do_not_claim_completion(profile_server):
    async def run():
        from core.computer_use.browser import BrowserAdapter
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True)
            try:
                page=await browser.new_page();adapter=BrowserAdapter(page)
                obs=(await adapter.open(profile_server[0]))['observation']
                moved=await adapter.act(obs['observation_id'],'scroll',amount=700)
                assert moved['success'] and await page.evaluate('scrollY')>0
                stale=await adapter.act(obs['observation_id'],'click',target(obs,'Footer'))
                assert stale['error']=='StaleObservation'
                result=await adapter.act(stale['observation']['observation_id'],'wait',value='Never appears',timeout_ms=50)
                assert not result['success'] and result['error']=='BrowserTimeout'
                assert profile_server[1]['saved'] is None
            finally: await browser.close()
    asyncio.run(run())


def test_insecure_http_observation_does_not_require_crypto_random_uuid():
    # A real browser on an HTTP origin without crypto.randomUUID still observes.
    async def run():
        from core.computer_use.browser import BrowserAdapter
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True)
            try:
                page=await browser.new_page()
                await page.route('http://insecure.example/',lambda route:route.fulfill(body='<button>Save</button>',content_type='text/html'))
                await page.goto('http://insecure.example/')
                assert await page.evaluate('typeof crypto.randomUUID')=='undefined'
                assert (await BrowserAdapter(page).observe())['targets'][0]['label']=='Save'
            finally: await browser.close()
    asyncio.run(run())


def test_navigation_timeout_does_not_claim_click_was_not_applied():
    async def run():
        from core.computer_use.browser import BrowserAdapter
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True)
            try:
                page=await browser.new_page()
                navigation = []
                async def delayed(route):
                    navigation.append(route.request.url)
                    await asyncio.sleep(1.5)
                    await route.abort()
                await page.route('http://delayed.example/',delayed)
                await page.set_content('<button onclick="window.clicked=true;location.href=\'http://delayed.example/\'">Go</button>')
                adapter=BrowserAdapter(page);obs=await adapter.observe()
                result=await adapter.act(obs['observation_id'],'click',target(obs,'Go'),timeout_ms=500)
                assert result['error']=='BrowserTimeout' and result['outcome']=='tool_error'
                assert result['action_applied'] is None
                assert navigation == ['http://delayed.example/']
            finally: await browser.close()
    asyncio.run(run())


def test_scrolling_exposes_controls_beyond_document_order_cap():
    async def run():
        from core.computer_use.browser import BrowserAdapter
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True)
            try:
                page=await browser.new_page()
                await page.set_content(''.join(f'<button style="display:block;height:45px">Button {i}</button>' for i in range(80))+'<button style="display:block;height:45px" onclick="this.textContent=\'Reached last\'">Last button</button>')
                adapter=BrowserAdapter(page);obs=await adapter.observe()
                assert obs['truncated'] and not any(t['label']=='Last button' for t in obs['targets'])
                moved=await adapter.act(obs['observation_id'],'scroll',amount=2000)
                moved=await adapter.act(moved['observation']['observation_id'],'scroll',amount=2000)
                obs=moved['observation']
                result=await adapter.act(obs['observation_id'],'click',target(obs,'Last button'))
                assert result['success'] and 'Reached last' in result['observation']['text']
            finally: await browser.close()
    asyncio.run(run())


def test_changed_link_destination_rejects_old_observation():
    async def run():
        from core.computer_use.browser import BrowserAdapter
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True)
            try:
                page=await browser.new_page()
                await page.route('http://example.test/**',lambda route:route.fulfill(body='Wrong destination'))
                await page.set_content('<a href="http://example.test/one">Open</a>')
                adapter=BrowserAdapter(page);obs=await adapter.observe()
                await page.evaluate('document.querySelector("a").href="http://example.test/two"')
                result=await adapter.act(obs['observation_id'],'click',target(obs,'Open'))
                assert result['error']=='StaleObservation' and page.url=='about:blank'
            finally: await browser.close()
    asyncio.run(run())


def test_changed_form_destination_rejects_old_submit_button():
    async def run():
        from core.computer_use.browser import BrowserAdapter
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True)
            try:
                page=await browser.new_page();requests=[]
                async def receive(route):
                    requests.append(route.request.url)
                    await route.fulfill(body='Unexpected submission')
                await page.route('http://example.test/**',receive)
                await page.set_content('<form action="http://example.test/one" method="post"><button>Submit</button></form>')
                adapter=BrowserAdapter(page);obs=await adapter.observe()
                await page.evaluate('document.querySelector("form").action="http://example.test/two"')
                result=await adapter.act(obs['observation_id'],'click',target(obs,'Submit'))
                assert result['error']=='StaleObservation' and requests==[]
            finally: await browser.close()
    asyncio.run(run())
