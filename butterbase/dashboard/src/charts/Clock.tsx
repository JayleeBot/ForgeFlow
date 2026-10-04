import { FOLLOW_UP_BUSINESS_DAYS } from "../data";
import type { ClockStatus, FollowUp } from "../data";
import { STATUS } from "./palette";

const COLOR: Record<ClockStatus, string> = {
  on_track: STATUS.good,
  due_soon: STATUS.warning,
  overdue: STATUS.critical,
};

/** Status mark: a shape per state, so the state reads without colour too. */
export function ClockIcon({ status }: { status: ClockStatus | "pending" }) {
  if (status === "pending") {
    return (
      <svg className="clock-icon" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="5.5" fill="none" stroke="var(--muted)" strokeWidth="1.5" strokeDasharray="2.5 2" />
      </svg>
    );
  }
  const color = COLOR[status];
  return (
    <svg className="clock-icon" viewBox="0 0 16 16" aria-hidden="true">
      {status === "on_track" && (
        <>
          <circle cx="8" cy="8" r="7" fill={color} />
          <path d="M4.8 8.3l2.1 2.1 4.3-4.6" fill="none" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </>
      )}
      {status === "due_soon" && (
        <>
          <circle cx="8" cy="8" r="7" fill={color} />
          <path d="M8 4.4V8l2.4 1.6" fill="none" stroke="#3d2a00" strokeWidth="1.8" strokeLinecap="round" />
        </>
      )}
      {status === "overdue" && (
        <>
          <path d="M8 1.2l7 12.6H1z" fill={color} strokeLinejoin="round" />
          <path d="M8 5.6v3.8" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" />
          <circle cx="8" cy="11.7" r="1" fill="#fff" />
        </>
      )}
    </svg>
  );
}

/**
 * The follow-up window as a meter: one segment per business day, filled as
 * days pass, coloured by how close the deadline is. Overdue fills it entirely.
 */
export function ClockMeter({ followUp }: { followUp: FollowUp }) {
  const used = Math.min(Math.max(FOLLOW_UP_BUSINESS_DAYS - followUp.daysLeft, 0), FOLLOW_UP_BUSINESS_DAYS);
  const color = COLOR[followUp.status];
  return (
    <span className="meter" role="img"
      aria-label={`${used} of ${FOLLOW_UP_BUSINESS_DAYS} business days used`}>
      {Array.from({ length: FOLLOW_UP_BUSINESS_DAYS }, (_, i) => (
        <span key={i} className="meter-seg" style={i < used || followUp.status === "overdue" ? { background: color } : undefined} />
      ))}
    </span>
  );
}
