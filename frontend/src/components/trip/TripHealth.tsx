import { RouteIcon } from "../icons";
import { cx } from "../ui/cx";
import {
  healthCopy,
  runItineraryChecks,
  type HealthCopy,
  type ItineraryCheck,
} from "../../lib/itineraryCheck";
import type { Day, Stop } from "../../types/trip";
import styles from "./TripHealth.module.css";

type Props = {
  days: Day[];
  request?: { start_date?: string | null } | null;
  backlog?: Stop[] | null;
  lang?: "zh" | "en";
  className?: string;
};

function titleFor(check: ItineraryCheck, copy: HealthCopy): string {
  switch (check.code) {
    case "closed_day":
      return copy.closedDayTitle(check.day);
    case "weekly_closure":
      return copy.weeklyTitle(check.places.length);
    case "long_hop":
      return copy.longHopTitle(check.day);
    case "heavy_day":
      return copy.heavyTitle(check.day);
    case "duplicate_place":
      return copy.duplicateTitle;
  }
}

function detailFor(check: ItineraryCheck, copy: HealthCopy, lang: "zh" | "en"): string {
  switch (check.code) {
    case "closed_day":
      return copy.closedDayDetail(check.place, copy.weekday(check.weekday));
    case "weekly_closure": {
      const visible = check.places.slice(0, 3);
      const separator = lang === "zh" ? "、" : ", ";
      const items = visible.map(item => copy.weeklyItem(item.name, item.closedDays.map(copy.weekday).join(separator)));
      return copy.weeklyDetail(items, Math.max(0, check.places.length - visible.length));
    }
    case "long_hop":
      return copy.longHopDetail(check.from, check.to, check.km.toFixed(1));
    case "heavy_day": {
      const hours = (check.minutes / 60).toFixed(1).replace(/\.0$/, "");
      return copy.heavyDetail(check.stops, hours);
    }
    case "duplicate_place":
      return copy.duplicateDetail(check.name, check.count);
  }
}

/**
 * 行程体检卡只显示“高置信”的问题；没有问题时不渲染，避免用一张空卡占首屏。
 */
export function TripHealth({ days, request, backlog, lang = "zh", className }: Props) {
  const checks = runItineraryChecks({ days, request, backlog });
  const copy = healthCopy(lang);
  if (!checks.length) return null;
  return (
    <section className={cx(styles.card, className)} aria-label={copy.ariaLabel} data-health-count={checks.length}>
      <div className={styles.head}>
        <span className={styles.icon} aria-hidden="true"><RouteIcon size={16} /></span>
        <span className={styles.title}>{copy.sectionTitle}</span>
        <span className={styles.count}>{copy.count(checks.length)}</span>
      </div>
      <ul className={styles.list}>
        {checks.map((check, index) => (
          <li key={check.code + "-" + index} className={styles.item} data-severity={check.severity} data-health-code={check.code}>
            <span className={styles.dot} aria-hidden="true" />
            <span className={styles.body}>
              <span className={styles.itemTitle}>{titleFor(check, copy)}</span>
              <span className={styles.itemDetail}>{detailFor(check, copy, lang)}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
