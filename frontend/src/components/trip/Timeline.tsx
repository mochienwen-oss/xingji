import { useMemo } from 'react';
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import type { Day, Stop } from '../../types/trip';
import { formatFixedTime, formatRange, formatTime } from '../../lib/schedule';
import { ClockIcon, DragIcon, PlusIcon } from '../icons';
import { Button } from '../ui/Button';
import { cx } from '../ui/cx';
import { PlaceTrustBadge } from './PlaceTrust';
import { RouteSegment } from './RouteSegment';
import { stopTitle, transportLabel } from './workspace';
import styles from './TripWorkspace.module.css';

type ScheduledStop = {
  arrival: number | null;
  start: number | null;
  departure: number | null;
  fixed: number | null;
  late: boolean;
};

type TimelineProps = {
  day: Day;
  dayIndex: number;
  transport: string;
  dirty: boolean;
  busy: boolean;
  routeBusy: boolean;
  backlogCount: number;
  scheduled: ScheduledStop[];
  onOpenStop: (index: number) => void;
  onReorder: (from: number, to: number) => void;
  onRecomputeRoutes: () => void;
  onOpenBacklog: () => void;
  onOpenNearby: () => void;
};

function StopRow({
  stop,
  index,
  scheduled,
  busy,
  onOpen,
}: {
  stop: Stop;
  index: number;
  scheduled?: ScheduledStop;
  busy: boolean;
  onOpen: () => void;
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } =
    useSortable({ id: stop.place.id, disabled: busy });

  // 开始时间缺失或前一段没有路线时排不出时间，但固定事项仍要显示（含「次日」）。
  const time = scheduled?.start != null ? formatTime(scheduled.start) : formatFixedTime(stop.fixed_time, !!stop.fixed_next_day);
  const range = formatRange(scheduled?.start ?? null, scheduled?.departure ?? null);
  const meta = stop.activity?.trim()
    ? `${stop.place.name} · ${stop.place.address || '地址暂无信息'}`
    : stop.place.address || '地址暂无信息';

  return (
    <div
      ref={setNodeRef}
      className={cx(styles.stopRow, isDragging && styles.stopDragging)}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      data-testid={`stop-row-${stop.place.id}`}
    >
      <button
        type="button"
        className={styles.stopMain}
        onClick={onOpen}
        aria-label={`第 ${index + 1} 站：${stopTitle(stop)}，查看详情`}
      >
        <span className={styles.stopIndex}>
          <span className={styles.stopOrder}>{String(index + 1).padStart(2, '0')}</span>
          <span className={cx(styles.stopTime, !time && styles.stopTimePending)}>
            {time || '待定'}
          </span>
        </span>
        <span className={styles.stopBody}>
          <span className={styles.stopName}>{stopTitle(stop)}</span>
          <span className={styles.stopMeta}>
            <span className={styles.stopAddress}>{meta}</span>
            <span className={styles.stopFlags}>
              <span className={styles.stopDuration} title={range ? `停留 ${stop.duration} 分钟` : undefined}>
                <ClockIcon size={14} /> {range ?? `停留 ${stop.duration} 分钟`}
              </span>
              <PlaceTrustBadge place={stop.place} />
            </span>
          </span>
        </span>
      </button>
      <button
        ref={setActivatorNodeRef}
        type="button"
        className={styles.dragHandle}
        aria-label={`拖动「${stopTitle(stop)}」调整顺序`}
        disabled={busy}
        {...attributes}
        {...listeners}
      >
        <DragIcon />
      </button>
    </div>
  );
}

/** 64px 站点行、站点间路线段与空天状态。 */
export function Timeline({
  day,
  dayIndex,
  transport,
  dirty,
  busy,
  routeBusy,
  backlogCount,
  scheduled,
  onOpenStop,
  onReorder,
  onRecomputeRoutes,
  onOpenBacklog,
  onOpenNearby,
}: TimelineProps) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const ids = useMemo(() => day.stops.map(stop => stop.place.id), [day.stops]);

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from < 0 || to < 0) return;
    onReorder(from, to);
  }

  if (day.stops.length === 0) {
    return (
      <div className={styles.emptyDay}>
        <span className={styles.emptyIcon} aria-hidden="true">
          <PlusIcon size={28} />
        </span>
        <p className={styles.emptyTitle}>这一天还没有安排</p>
        <p className={styles.emptyHint}>从待规划里挑一个地点，或者问问 AI 怎么排。</p>
        <Button variant="secondary" onClick={onOpenBacklog} disabled={busy || backlogCount === 0}>
          从待规划添加
        </Button>
        <Button variant="text" onClick={onOpenNearby} disabled={busy}>
          探索附近地点
        </Button>
        {backlogCount === 0 ? <p className={styles.emptyHint}>待规划中暂时没有地点，也可以从附近找。</p> : null}
      </div>
    );
  }

  return (
    <div className={styles.timeline} aria-label={`第 ${dayIndex + 1} 天时间线，${transportLabel(transport)}出行`}>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={ids} strategy={verticalListSortingStrategy}>
          {day.stops.map((stop, index) => (
            <div key={stop.place.id} className={styles.timelineItem}>
              <StopRow
                stop={stop}
                index={index}
                scheduled={scheduled[index]}
                busy={busy}
                onOpen={() => onOpenStop(index)}
              />
              {index < day.stops.length - 1 ? (
                <RouteSegment
                  route={day.routes[index]}
                  fallbackMode={transport}
                  dirty={dirty}
                  busy={routeBusy}
                  onRecompute={onRecomputeRoutes}
                />
              ) : null}
            </div>
          ))}
        </SortableContext>
      </DndContext>
      <div className={styles.addPlaceRow}>
        <Button variant="secondary" className={styles.addPlaceButton} onClick={onOpenNearby} disabled={busy}>
          添加附近地点
        </Button>
        {backlogCount > 0 ? (
          <Button variant="text" onClick={onOpenBacklog} disabled={busy}>
            待规划 {backlogCount}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

