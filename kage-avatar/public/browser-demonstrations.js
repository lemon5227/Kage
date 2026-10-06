/* A Page teaching card; consumes the Launcher's public job event and HTTP helper. */
window.KageBrowserDemonstrations = {
  init({request, apiUrl}) {
    const el = id => document.getElementById('demonstration-' + id);
    const base = '/browser/demonstrations';
    const terminal = new Set(['verified', 'completed', 'incomplete', 'failed', 'stopped']);
    let catalog, current, candidateJob, generation = 0, poll, sequence = 0, applied = 0;
    let locked = false, busy = false, finishSent = false;
    const active = () => current && !terminal.has(current.status);
    const controls = () => {
      el('start').disabled = busy || active() || !catalog;
      el('finish').disabled = busy || finishSent || !current?.ready || current.operation !== 'demonstration';
      el('stop').disabled = busy || !active();
      el('history').disabled = busy || active();
      el('task').disabled = busy || active();
      el('source').disabled = busy || active();
      el('replay').disabled = busy || active() || !candidateJob;
    };
    const selection = () => {
      el('goal').textContent = catalog?.tasks.find(t => t.task_id === el('task').value)?.instruction || '';
      el('reuse-goal').textContent = catalog?.tasks.find(t => t.task_id === el('reuse-task').value)?.instruction || '';
    };
    const showCandidate = job => {
      candidateJob = job?.status === 'verified' && job.result?.candidate ? job : null;
      el('candidate').hidden = !candidateJob;
      if (!candidateJob) return;
      const task = catalog.tasks.find(t => t.task_id === job.task_id);
      el('reuse-task').replaceChildren();
      for (const item of catalog.tasks.filter(t => t.task_id.startsWith('reuse_') && t.family === task.family)) {
        const option = document.createElement('option'); option.value = item.task_id; option.textContent = item.title;
        el('reuse-task').append(option);
      }
      el('arguments').value = JSON.stringify(job.result.candidate.arguments, null, 2);
      selection();
    };
    const render = job => {
      if (!job || job.run_id !== current?.run_id || locked) return;
      current = job;
      locked = terminal.has(job.status);
      const result = job.result || {};
      const labels = {queued: '排队中', starting: '启动中', recording: '录制中', finalizing: '保存检查与提取中',
        verified: '示范检查通过 · 候选已生成（未晋级）', completed: '复用检查通过', incomplete: '示范不完整', failed: '执行失败', stopped: '已取消'};
      const lines = [`运行: ${job.run_id}`, `状态: ${labels[job.status] || job.status}`,
        `来源: ${job.source_kind}`, `执行者: ${job.executor}`, `动作数: ${job.event_count ?? 0}`,
        `独立检查: ${job.check_passed === true ? '通过' : job.check_passed === false ? '未通过' : '待确认'}`,
        '模型请求: 0', '费用 USD: 0 · 来源: local_api_only（仅本地 API）'];
      if (job.ready) lines.push('独立教学窗口已就绪，请按公开目标操作、保存后结束。');
      if (job.stop_reason) lines.push('停止原因: ' + job.stop_reason);
      if (job.error) lines.push('错误: ' + job.error);
      if (result.candidate_error) lines.push('候选错误: ' + result.candidate_error);
      if (result.candidate) lines.push('候选 digest: ' + result.candidate.digest, '候选未晋级 · 不代表 AI 学会');
      if (result.workflow_digest) lines.push('复用 digest: ' + result.workflow_digest);
      el('status').textContent = lines.join('\n');
      el('artifacts').replaceChildren();
      for (const item of job.artifacts || []) {
        const link = document.createElement('a'); link.textContent = item.name;
        link.href = apiUrl + item.url.slice(4); link.target = '_blank'; link.rel = 'noopener';
        el('artifacts').append(link);
      }
      if (job.status === 'verified') showCandidate(job);
      if (locked) {
        clearInterval(poll); poll = null;
        if (job.operation === 'demonstration') {
          if (![...el('history').options].some(o => o.value === job.run_id)) {
            const option = document.createElement('option'); option.value = job.run_id;
            option.textContent = `${job.task_id} · ${job.status} · ${job.run_id}`; el('history').append(option);
          }
        }
      }
      controls();
    };
    const bind = job => {
      generation++; clearInterval(poll); sequence = applied = 0; locked = false; finishSent = false;
      current = {run_id: job.run_id}; render(job);
      if (!locked) {
        const stamp = generation, id = job.run_id;
        poll = setInterval(async () => {
          const n = ++sequence;
          try {
            const updated = await request(`${base}/${id}`);
            if (generation !== stamp || current?.run_id !== id || n < applied || locked) return;
            applied = n; render(updated);
          } catch (error) {
            if (generation === stamp && !locked) el('error').textContent = '状态读取失败: ' + error;
          }
        }, 500);
      }
    };
    const action = async (kind, body) => {
      if (busy) return;
      const old = current?.run_id, stamp = generation;
      busy = true; el('error').textContent = ''; controls();
      try {
        const path = kind === 'start' ? base : `${base}/${kind === 'replay' ? candidateJob.run_id : old}/${kind}`;
        const job = await request(path, {method: 'POST', headers: {'content-type': 'application/json'},
          ...(body ? {body: JSON.stringify(body)} : {})});
        if (generation !== stamp || current?.run_id !== old) return;
        if (kind === 'start' || kind === 'replay') {
          if (kind === 'start') showCandidate(null);
          bind(job);
        } else {
          if (kind === 'finish') finishSent = true;
          render(job);
        }
      } catch (error) {
        if (generation === stamp) el('error').textContent = '请求失败: ' + error;
      } finally {
        busy = false; controls();
      }
    };
    el('task').addEventListener('change', selection);
    el('reuse-task').addEventListener('change', selection);
    el('start').addEventListener('click', () => action('start', {task_id: el('task').value, source_kind: el('source').value}));
    el('finish').addEventListener('click', () => action('finish'));
    el('stop').addEventListener('click', () => action('stop'));
    el('replay').addEventListener('click', () => {
      try { action('replay', {task_id: el('reuse-task').value, arguments: JSON.parse(el('arguments').value)}); }
      catch (error) { el('error').textContent = 'JSON 参数无效: ' + error; }
    });
    el('history').addEventListener('change', async () => {
      if (busy) return;
      const id = el('history').value, stamp = ++generation;
      clearInterval(poll); showCandidate(null);
      if (!id) { current = null; showCandidate(null); controls(); return; }
      busy = true; el('error').textContent = ''; controls();
      try {
        const job = await request(`${base}/${id}`);
        if (stamp === generation && el('history').value === id) { showCandidate(job); bind(job); }
      } catch (error) { if (stamp === generation) el('error').textContent = String(error); }
      finally { busy = false; controls(); }
    });
    window.addEventListener('kage:job', event => {
      const job = event.detail?.job;
      if (job?.task_type === 'browser_demonstration' && job.run_id === current?.run_id) render(job);
    });
    (async () => {
      const stamp = generation;
      try {
        const [loaded, jobs] = await Promise.all([request(base + '/catalog'), request(base)]);
        catalog = loaded;
        for (const task of catalog.tasks.filter(t => t.task_id.startsWith('demo_'))) {
          const option = document.createElement('option'); option.value = task.task_id; option.textContent = task.title;
          el('task').append(option);
        }
        for (const job of jobs.filter(j => terminal.has(j.status) && j.operation === 'demonstration')) {
          const option = document.createElement('option'); option.value = job.run_id;
          option.textContent = `${job.task_id} · ${job.status} · ${job.run_id}`; el('history').append(option);
        }
        selection();
        if (stamp === generation) {
          const running = jobs.find(j => !terminal.has(j.status));
          if (running) bind(running);
        }
      } catch (error) { el('error').textContent = '浏览器教学不可用: ' + error; }
      controls();
    })();
  }
};
