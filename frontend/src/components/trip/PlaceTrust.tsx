import { AlertIcon, CheckIcon } from "../icons";
import { cx } from "../ui/cx";
import {
  placeVerification,
  verificationCopy,
  verificationStats,
  verificationTitle,
  type VerificationLang,
} from "../../lib/verification";
import type { Place } from "../../types/trip";
import styles from "./PlaceTrust.module.css";

type BadgeProps = {
  place: Place;
  lang?: VerificationLang;
  className?: string;
};

/** 单个地点的核验标记：时间线、分享页共用，避免两套文案。 */
export function PlaceTrustBadge({ place, lang = "zh", className }: BadgeProps) {
  const verification = placeVerification(place);
  const copy = verificationCopy(lang);
  const label = verification.status === "verified"
    ? copy.verified
    : verification.status === "unavailable"
      ? copy.unavailable
      : copy.needsCheck;
  return (
    <span
      className={cx(styles.badge, styles[verification.status], className)}
      title={verificationTitle(place, lang)}
      data-verification={verification.status}
    >
      <span className={styles.badgeDot} aria-hidden="true" />
      {label}
    </span>
  );
}

type SummaryProps = {
  places: Place[];
  lang?: VerificationLang;
  className?: string;
};

/**
 * 行程级摘要只做一件事：把“已核验”和“出发前要确认”说清楚。
 * 不再堆第二个仪表盘；有未核验项时给出数量，全部核验时直接确认。
 */
export function PlaceTrustSummary({ places, lang = "zh", className }: SummaryProps) {
  const stats = verificationStats(places);
  if (stats.total === 0) return null;
  const copy = verificationCopy(lang);
  const allVerified = stats.verified === stats.total;
  const title = allVerified ? copy.summaryAll(stats.total) : copy.summaryTitle(stats.verified, stats.total);
  const hint = allVerified ? copy.hintAll : copy.hint(stats.needsCheck, stats.unavailable);
  const tone = allVerified ? "verified" : stats.unavailable > 0 ? "danger" : "attention";
  return (
    <div className={cx(styles.summary, styles[tone], className)} data-verification-summary={tone}>
      <span className={styles.summaryIcon} aria-hidden="true">
        {allVerified ? <CheckIcon size={18} /> : <AlertIcon size={18} />}
      </span>
      <span className={styles.summaryBody}>
        <span className={styles.summaryTitle}>{title}</span>
        <span className={styles.summaryHint}>{hint}</span>
      </span>
    </div>
  );
}
