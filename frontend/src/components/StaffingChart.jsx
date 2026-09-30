/** Light bar chart for staffing summary (CSS widths, no chart lib). */
export default function StaffingChart({ summary }) {
  const byKind = summary?.by_kind || {};
  const formalDays = byKind.formal?.person_day_total || 0;
  const contractDays = byKind.contract?.person_day_total || 0;
  const maxKind = Math.max(formalDays, contractDays, 1);

  if (!summary?.person_count) return null;

  return (
    <div className="staffing-chart">
      <div className="staffing-chart-block">
        <div className="staffing-chart-title">身份人天</div>
        <div className="staffing-bar-row">
          <span className="staffing-bar-label">正式我司</span>
          <div className="staffing-bar-track">
            <div
              className="staffing-bar-fill formal"
              style={{ width: `${(formalDays / maxKind) * 100}%` }}
            />
          </div>
          <span className="staffing-bar-value">{formalDays}</span>
        </div>
        <div className="staffing-bar-row">
          <span className="staffing-bar-label">机电服务处</span>
          <div className="staffing-bar-track">
            <div
              className="staffing-bar-fill contract"
              style={{ width: `${(contractDays / maxKind) * 100}%` }}
            />
          </div>
          <span className="staffing-bar-value">{contractDays}</span>
        </div>
      </div>
    </div>
  );
}
