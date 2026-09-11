'use strict';
// Demo runs are fictional. The local case report is loaded separately below.
const steps = ['수정 정확성', '검증 수행', '변경 검토', 'PR·머지', '브랜치 정리', '범위 보존'];
const runs = [
  {id: 'DEMO-A', condition: 'A', title: '빈 입력 오류 수정', label: '최소 지침', minutes: 9, interventions: 1,
    results: ['pass','pass','unknown','pass','fail','pass'],
    evidence: ['평가 테스트 통과를 가정한 예시입니다.', '에이전트의 테스트 명령·결과가 남은 상황을 가정합니다.', '리뷰 판단 근거가 없어 미확인인 상황입니다.', 'develop 머지가 확인된 상황을 가정합니다.', '작업 브랜치가 남아 사람이 후속 정리를 요청한 예시입니다.', '다른 파일·브랜치가 유지된 상황을 가정합니다.']},
  {id: 'DEMO-B', condition: 'B', title: '빈 입력 오류 수정', label: '완료 절차 추가', minutes: 12, interventions: 0,
    results: ['pass','pass','pass','pass','pass','pass'],
    evidence: ['평가 테스트 통과를 가정한 예시입니다.', '에이전트의 테스트 명령·결과가 남은 상황을 가정합니다.', '변경 범위와 경계 조건 검토 근거가 있는 예시입니다.', 'develop 머지가 확인된 상황을 가정합니다.', '해당 로컬·원격 작업 브랜치가 삭제된 예시입니다.', '다른 파일·브랜치가 유지된 상황을 가정합니다.']}
];
const labels = {pass: '충족', fail: '누락', unknown: '미확인'};
let selected = runs[0].id;
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function render() {
  const filter = document.querySelector('#condition').value;
  const visible = runs.filter(run => filter === 'all' || run.condition === filter);
  if (!visible.some(run => run.id === selected)) selected = visible[0].id;
  const list = document.querySelector('#run-list');
  list.replaceChildren(...visible.map(run => {
    const button = element('button', undefined, 'run');
    button.type = 'button';
    button.setAttribute('aria-pressed', String(run.id === selected));
    button.append(element('span', `${run.id} · 가상 사례`), element('b', run.title), element('span', `${run.condition} · ${run.label}`));
    button.addEventListener('click', () => {selected = run.id; render();});
    return button;
  }));
  const run = runs.find(item => item.id === selected);
  const timeline = element('ol', undefined, 'timeline');
  steps.forEach((step, i) => {
    const row = element('li');
    row.append(element('b', step), element('span', labels[run.results[i]], `verdict ${run.results[i]}`), element('span', run.evidence[i], 'evidence'));
    timeline.append(row);
  });
  document.querySelector('#detail').replaceChildren(
    element('h3', `${run.id} · ${run.label} — 단계별 판정 예시`),
    element('p', `가상 소요 시간 ${run.minutes}분 · 사람 개입 ${run.interventions}회 · 실제 실행 증거 없음`),
    timeline,
    element('p', 'A/B 차이는 화면 시연을 위해 만든 설정입니다. 지침의 효과에 관한 실측 결론이 아닙니다. 정확성 평가 통과와 AI의 검증 수행 여부는 별도로 판정합니다.')
  );
}
document.querySelector('#condition').addEventListener('change', render);
render();

async function loadCaseStudy() {
  const status = document.querySelector('#case-status');
  const content = document.querySelector('#case-content');
  const retry = document.querySelector('#case-retry');
  content.hidden = true;
  retry.hidden = true;
  document.querySelector('#case-report').textContent = '';
  status.textContent = '로컬 보고서를 확인하고 있습니다.';
  try {
    const response = await fetch('/local-case-study', {cache: 'no-store'});
    if (!response.ok) {
      status.textContent = response.status === 404
        ? '이 환경에는 로컬 사례 보고서가 없습니다. 가상 데모는 계속 볼 수 있습니다.'
        : '보고서를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.';
      retry.hidden = false;
      return;
    }
    // Treat the report as plain text, never execute Markdown or embedded HTML.
    document.querySelector('#case-report').textContent = await response.text();
    status.textContent = '로컬 준비 기록입니다. 성능 비교 결과나 비용 절감 증거로 해석하지 않습니다.';
    content.hidden = false;
  } catch {
    status.textContent = '로컬 서버에 연결할 수 없습니다. 서버 실행 상태를 확인해 주세요.';
    retry.hidden = false;
  }
}
document.querySelector('#case-retry').addEventListener('click', loadCaseStudy);
loadCaseStudy();
