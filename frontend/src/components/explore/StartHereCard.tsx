import { Kicker } from '../ui/Kicker';
import styles from './StartHereCard.module.css';

const STEPS = [
  { index: '01', title: '选一座城', body: '或直接说出想法，不必先定位。' },
  { index: '02', title: 'AI 用真实地点成稿', body: '地点来自高德实搜，路线可调整。' },
  { index: '03', title: '在地图上边看边改', body: '收藏想去的地方，最后确认就出发。' },
];

export function StartHereCard() {
  return (
    <section className={styles.card} aria-labelledby="explore-guide-title">
      <Kicker>第一次来行迹</Kicker>
      <h3 id="explore-guide-title" className={styles.title}>把想法变成一条能走的路线</h3>
      <ol className={styles.steps}>
        {STEPS.map((step) => (
          <li key={step.index} className={styles.step}>
            <span className={styles.index} aria-hidden="true">{step.index}</span>
            <span className={styles.stepBody}>
              <span className={styles.stepTitle}>{step.title}</span>
              <span className={styles.stepText}>{step.body}</span>
            </span>
          </li>
        ))}
      </ol>
      <p className={styles.note}>没有定位也能用：选一个城市，或直接说想去哪。</p>
    </section>
  );
}
