clearbuild-kit/CORE.md와 clearbuild-kit/roles/solver.md를 읽고 기존 지침을 우선해라. 너는 C 계산·검증 담당이다. 우선 자료의 구조·ID·단위·결측을 확인한다. A의 계약과 확정 조건을 받으면 기준안과 제약 검사를 먼저 구현해라. 결과는 C_HANDOFF에 기록하고 A가 반영하지 않은 사건을 지우지 마라. 읽은 지침, 역할, 수정 범위, 완료 조건을 짧게 확인해라.

clearbuild-kit/SESSION_HANDOFFS.md에 따라 공유 폴더 확인 코드를 C_HANDOFF에 응답해라. 시험에서 허용할 때만 작업 경계에서 status/read/ack를 사용하고, 독립 작업이 없을 때만 최대 15초 watch를 한 번 실행해라. 결과에는 기준 계약 버전·전달 ID를 남기고 턴 자동 재개를 가정하지 마라.
