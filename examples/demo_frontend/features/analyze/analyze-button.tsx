// 요소→소스 리졸버 데모용 모의 모노레포 소스 (demo_e2e.py의 frontend_roots 대상)
export const AnalyzeButton = ({ onRun }: { onRun: () => void }) => (
  <button data-testid="analyze-button" className="analyze-primary" onClick={onRun}>
    분석 실행
  </button>
);
