# ClearBuild Kit
짧은 지침을 이용한 수동 다중 세션 협업 패키지. 자동 에이전트, 파일 잠금, 실시간 동기화 기능은 없다. 기존 작업 지침과 운영 규칙이 우선이다. 프로젝트 원본을 보존하고 기존 AGENTS.md나 설정을 덮어쓰지 않는다.

## 시작
허용된 환경의 프로젝트에서 `git clone --depth 1 <공개_저장소_URL> clearbuild-kit`으로 내려받는다. 대상이 이미 있으면 덮어쓰지 않는다. 지침은 자동 실행되지 않는다. 같은 실제 프로젝트에서 별도 Codex 세션을 열고 각 세션에 다음을 각각 입력한다.
- A: `clearbuild-kit/prompts/start_a.md를 읽고 진행해.`
- B: `clearbuild-kit/prompts/start_b.md를 읽고 진행해.`
- C: `clearbuild-kit/prompts/start_c.md를 읽고 진행해.`
프롬프트 안의 CORE.md와 roles 경로는 이 저장소 루트 기준이다. 필요하면 명시적으로 `clearbuild-kit/CORE.md`처럼 전체 경로를 알려준다. A가 계약을 만들기 전 B/C는 독립적인 환경·자료 조사만 한다.

## 협업 파일
A가 실제 프로젝트의 비어 있는 worklog 폴더에 templates/PROJECT.md, DECISIONS.md를 복사하고 HANDOFF.md를 B_HANDOFF.md와 C_HANDOFF.md로 각각 복사한다. 충돌 시 기존 파일을 덮어쓰지 말고 새 경로를 사용자와 정한다. A는 PROJECT와 DECISIONS, B와 C는 자기 HANDOFF만 작성한다. 세션 간 자동 통신이 없으므로 사용자가 A에게 전달 파일을 다시 읽으라고 알리고, B/C에게 PROJECT의 변경을 다시 읽으라고 알린다. 담당자 답변은 사용자가 원문을 A에 붙여넣는다. 자동 폴링은 없다.

## 우선순위
문제의 완전한 분석을 기다리기 전에 환경 조사와 안전한 독립 작업을 시작한다. 계약 후 작은 실제 입력 하나를 끝까지 연결한다. 불필요한 관리 MD 생성을 피하되 필수 산출물은 만든다. 공개 저장소에 개인 정보나 작업 자료를 넣지 않는다. 제공 환경 및 정책에 맞지 않는 기능을 우회하지 않는다.
