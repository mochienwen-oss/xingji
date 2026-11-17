import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { usePageActive } from "../app/providers/PageActiveProvider";
import { useConfirm, useToast } from "../app/providers/ToastProvider";
import { CloseIcon, ShareIcon, UserMinusIcon } from "./icons";
import { Button } from "./ui/Button";
import { SegmentedControl } from "./ui/SegmentedControl";
import { api, ApiError, message } from "../lib/api";
import { maskShareLink, shareToken, shareUrl } from "../lib/shareLink";
import { useFocusTrap } from "../lib/useFocusTrap";
import type { Collaborator } from "../types/trip";
import styles from "./SharePanel.module.css";

/** 分享码要整段复制；剪贴板不可用时退回到 textarea + execCommand。 */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // 权限被拒或非安全上下文，继续尝试降级方案。
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "0";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = typeof document.execCommand === "function" ? document.execCommand("copy") : false;
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}

type Visibility = "private" | "link" | "public";

type SharePanelProps = {
  tripId: number;
  dirty: boolean;
  /** 只有 owner 能生成邀请、移除成员或切换公开状态。默认 true 以兼容现有调用。 */
  isOwner?: boolean;
  /** 行程当前是否已公开；父组件有该字段时传入，否则以保存后返回值为准。 */
  isPublic?: boolean;
  /** 协作者退出后回到列表/首页；不传则整页刷新。 */
  onLeave?: () => void;
};

export function SharePanel({ tripId, dirty, isOwner = true, isPublic, onLeave }: SharePanelProps) {
  const confirm = useConfirm();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const [members, setMembers] = useState<Collaborator[] | null>(null);
  const [membersBusy, setMembersBusy] = useState(false);
  const [membersError, setMembersError] = useState("");
  const [membersNotice, setMembersNotice] = useState("");
  const [removing, setRemoving] = useState<number | null>(null);
  const [leaveBusy, setLeaveBusy] = useState(false);
  const [leaveError, setLeaveError] = useState("");

  const [inviteLink, setInviteLink] = useState("");
  const [inviteExpiresAt, setInviteExpiresAt] = useState("");
  const [inviteBusy, setInviteBusy] = useState(false);
  const [revokeInvitesBusy, setRevokeInvitesBusy] = useState(false);
  const [inviteNotice, setInviteNotice] = useState("");
  const [inviteError, setInviteError] = useState("");

  const [visibility, setVisibility] = useState<Visibility>(isPublic ? "public" : "private");
  const [linkActive, setLinkActive] = useState(false);
  const [visibilityBusy, setVisibilityBusy] = useState(false);
  const [visibilityNotice, setVisibilityNotice] = useState("");
  const [visibilityError, setVisibilityError] = useState("");

  const [joinCode, setJoinCode] = useState("");
  const [joinCodeHidden, setJoinCodeHidden] = useState(false);
  const [joinCodeLoading, setJoinCodeLoading] = useState(false);
  const [joinCodeBusy, setJoinCodeBusy] = useState(false);
  const [joinCodeNotice, setJoinCodeNotice] = useState("");
  const [joinCodeError, setJoinCodeError] = useState("");

  const dialogRef = useRef<HTMLDivElement | null>(null);
  const pageActive = usePageActive();
  // 首焦点落在面板本身：打开瞬间不会把「关闭」顶成高亮描边，Tab 一次即到关闭键。
  useFocusTrap(dialogRef, { active: open && pageActive, onClose: () => setOpen(false), initialFocus: dialogRef });

  // 行程页被路由收起时关掉 portal，别让分享面板浮在其他页面上；回到行程可重新打开。
  useEffect(() => {
    if (!pageActive) setOpen(false);
  }, [pageActive]);

  useEffect(() => {
    if (typeof isPublic === "boolean") setVisibility(isPublic ? "public" : "private");
  }, [isPublic]);

  useEffect(() => {
    if (open && tripId !== 0) {
      void loadMembers();
      void loadStatus();
      void loadJoinCode();
    }
    // 打开面板时刷新一次，保证刚被邀请/移除的成员和链接状态都是最新的。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, tripId]);

  async function loadStatus() {
    try {
      const result = await api<{ visibility: Visibility; link_active: boolean }>("/trips/" + tripId + "/share-status");
      setVisibility(result.visibility);
      setLinkActive(result.link_active);
    } catch {
      // 状态读取失败不阻断分享面板：保留父组件传入的 is_public，用户仍可手动切换。
    }
  }

  async function loadMembers() {
    setMembersBusy(true);
    setMembersError("");
    try {
      const result = await api<{ members: Collaborator[] }>(`/trips/${tripId}/collaborators`);
      setMembers(result.members);
    } catch (e) {
      setMembersError(message(e));
    } finally {
      setMembersBusy(false);
    }
  }

  async function loadJoinCode() {
    if (!isOwner) return;
    setJoinCodeLoading(true);
    try {
      const result = await api<{ code: string | null }>(`/trips/${tripId}/join-code`);
      setJoinCode(result.code ?? "");
      setJoinCodeHidden(false);
      setJoinCodeError("");
    } catch (e) {
      // 非 owner 拿不到分享码：整块静默隐藏，不打扰面板其它区块。
      if (e instanceof ApiError && (e.status === 403 || e.status === 404)) {
        setJoinCodeHidden(true);
      } else {
        setJoinCodeError(message(e));
      }
    } finally {
      setJoinCodeLoading(false);
    }
  }

  async function createJoinCode() {
    if (joinCodeBusy) return;
    setJoinCodeBusy(true);
    setJoinCodeError("");
    setJoinCodeNotice("");
    try {
      const result = await api<{ code: string }>(`/trips/${tripId}/join-code`, {
        method: "POST",
        body: JSON.stringify({ rotate: false }),
      });
      setJoinCode(result.code);
      setJoinCodeNotice("分享码已生成，复制后发给朋友。");
    } catch (e) {
      setJoinCodeError(message(e));
    } finally {
      setJoinCodeBusy(false);
    }
  }

  async function copyJoinCode() {
    const copied = await copyText(joinCode);
    if (copied) toast("分享码已复制", "success");
    else toast("请手动复制分享码", "error");
  }

  async function rotateJoinCode() {
    if (!joinCode || joinCodeBusy) return;
    const ok = await confirm({
      title: "重置分享码？",
      body: "重置后旧分享码立即失效，已加入的成员不受影响。",
      confirmLabel: "重置",
      cancelLabel: "取消",
      danger: true,
    });
    if (!ok) return;
    setJoinCodeBusy(true);
    setJoinCodeError("");
    setJoinCodeNotice("");
    try {
      const result = await api<{ code: string }>(`/trips/${tripId}/join-code`, {
        method: "POST",
        body: JSON.stringify({ rotate: true }),
      });
      setJoinCode(result.code);
      toast("分享码已重置", "success");
    } catch (e) {
      setJoinCodeError(message(e));
    } finally {
      setJoinCodeBusy(false);
    }
  }

  async function disableJoinCode() {
    if (!joinCode || joinCodeBusy) return;
    const ok = await confirm({
      title: "停用分享码？",
      body: "停用后朋友将无法再用这个分享码加入行程，已加入的成员不受影响。",
      confirmLabel: "停用",
      cancelLabel: "取消",
      danger: true,
    });
    if (!ok) return;
    setJoinCodeBusy(true);
    setJoinCodeError("");
    setJoinCodeNotice("");
    try {
      await api(`/trips/${tripId}/join-code`, { method: "DELETE" });
      setJoinCode("");
      toast("分享码已停用", "success");
    } catch (e) {
      setJoinCodeError(message(e));
    } finally {
      setJoinCodeBusy(false);
    }
  }

  async function create() {
    if (link && !(await confirm({ title: "重新生成分享链接？", body: "刚才的分享链接会立即失效，持有旧链接的人将无法再打开。", confirmLabel: "重新生成", cancelLabel: "取消", danger: true }))) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<{ token: string }>(`/trips/${tripId}/share`, { method: "POST" });
      setLink(shareUrl(result.token));
      setLinkActive(true);
      if (visibility !== "public") setVisibility("link");
      setNotice(link ? "新链接已生成，之前的分享链接已失效。" : "链接已生成，请复制后自行发送。");
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  async function revokeCurrentLink() {
    const token = shareToken(link);
    if (!token) return;
    if (!(await confirm({ title: "撤销这条分享链接？", body: "持有它的人将无法再打开这份行程。", confirmLabel: "撤销链接", cancelLabel: "保留", danger: true }))) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(`/shares/${encodeURIComponent(token)}`, { method: "DELETE" });
      setLink("");
      setLinkActive(false);
      if (visibility === "link") setVisibility("private");
      setNotice("已撤销这条分享链接。");
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  async function revoke() {
    if (!(await confirm({ title: "撤销全部分享链接？", body: "已发出的所有链接都会立即失效。", confirmLabel: "全部撤销", cancelLabel: "取消", danger: true }))) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(`/trips/${tripId}/share`, { method: "DELETE" });
      setLink("");
      setLinkActive(false);
      if (visibility === "link") setVisibility("private");
      setNotice("已撤销所有分享链接");
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  async function copyShareLink() {
    try {
      await navigator.clipboard.writeText(link);
      setNotice("链接已复制");
    } catch {
      setNotice("复制失败，请重试");
    }
  }

  async function createInvite() {
    if (!isOwner) return;
    setInviteBusy(true);
    setInviteError("");
    setInviteNotice("");
    try {
      const result = await api<{ token: string; expires_at?: string }>(
        `/trips/${tripId}/collaborators/invite`,
        { method: "POST" },
      );
      setInviteLink(`${window.location.origin}${window.location.pathname}#invite=${result.token}`);
      setInviteExpiresAt(result.expires_at || "");
      setInviteNotice("邀请链接已生成，复制后发给朋友。");
    } catch (e) {
      setInviteError(message(e));
    } finally {
      setInviteBusy(false);
    }
  }

  async function copyInviteLink() {
    try {
      await navigator.clipboard.writeText(inviteLink);
      setInviteNotice("邀请链接已复制");
    } catch {
      setInviteNotice("请选中链接后手动复制");
    }
  }

  async function revokeInvites() {
    if (!(await confirm({ title: "撤销未使用的邀请？", body: "已经发出去的邀请链接会立即失效。", confirmLabel: "撤销邀请", cancelLabel: "取消", danger: true }))) return;
    setRevokeInvitesBusy(true);
    setInviteError("");
    setInviteNotice("");
    try {
      const result = await api<{ revoked: number }>(`/trips/${tripId}/invites`, {
        method: "DELETE",
      });
      setInviteLink("");
      setInviteExpiresAt("");
      setInviteNotice(
        result.revoked > 0
          ? `已撤销 ${result.revoked} 个未使用的邀请。`
          : "当前没有未使用的邀请。",
      );
    } catch (e) {
      setInviteError(message(e));
    } finally {
      setRevokeInvitesBusy(false);
    }
  }

  const inviteValidity = (() => {
    if (!inviteExpiresAt) return "";
    const end = new Date(inviteExpiresAt).getTime();
    if (Number.isNaN(end)) return "仅可使用一次";
    const days = Math.max(1, Math.ceil((end - Date.now()) / 86_400_000));
    return `${days} 天内有效 · 仅可使用一次`;
  })();

  async function removeMember(member: Collaborator) {
    if (!isOwner) return;
    if (!(await confirm({ title: `移除协作者「${member.username}」？`, body: "对方将无法再编辑此行程，未使用的邀请链接也会一并失效。", confirmLabel: "移除成员", cancelLabel: "取消", danger: true }))) return;
    setRemoving(member.user_id);
    setMembersError("");
    setMembersNotice("");
    try {
      await api(`/trips/${tripId}/collaborators/${member.user_id}`, { method: "DELETE" });
      setMembers((current) => (current || []).filter((item) => item.user_id !== member.user_id));
      setMembersNotice(`已移除「${member.username}」，未使用的邀请链接同时失效。`);
      setInviteLink("");
      setInviteExpiresAt("");
    } catch (e) {
      setMembersError(message(e));
    } finally {
      setRemoving(null);
    }
  }

  async function leaveTrip() {
    if (isOwner) return;
    if (!(await confirm({ title: "退出这个行程？", body: "退出后你将不能再查看或编辑这份行程，需要重新接受邀请才能回来。", confirmLabel: "退出行程", cancelLabel: "留下", danger: true }))) return;
    setLeaveBusy(true);
    setLeaveError("");
    try {
      await api(`/trips/${tripId}/members/me`, { method: "DELETE" });
      if (onLeave) onLeave();
      else window.location.reload();
    } catch (e) {
      setLeaveError(message(e));
      setLeaveBusy(false);
    }
  }

  async function chooseVisibility(next: Visibility) {
    if (!isOwner || visibilityBusy || next === visibility) return;
    if (next === "private" && (linkActive || visibility === "public")) {
      const ok = await confirm({
        title: "收回这份行程？",
        body: "现有分享链接会立即失效，行程也会从灵感广场移除。已经复制走的副本不受影响。",
        confirmLabel: "设为私密",
        cancelLabel: "取消",
        danger: true,
      });
      if (!ok) return;
    }
    setVisibilityBusy(true);
    setVisibilityError("");
    setVisibilityNotice("");
    try {
      const result = await api<{ visibility: Visibility; is_public: boolean; link_active: boolean; token?: string }>(
        `/trips/${tripId}/visibility`,
        { method: "PUT", body: JSON.stringify({ mode: next }) },
      );
      setVisibility(result.visibility);
      setLinkActive(result.link_active);
      if (result.token) setLink(shareUrl(result.token));
      setVisibilityNotice(
        result.visibility === "public"
          ? "已公开到灵感广场。公开内容会自动脱敏，只显示城市、天数和行程结构。"
          : result.visibility === "link"
            ? "仅持链接的人可以查看这份行程的完整内容。"
            : "已设为私密：分享链接已撤销，广场也不再展示。",
      );
    } catch (e) {
      setVisibilityError(message(e));
    } finally {
      setVisibilityBusy(false);
    }
  }

  if (!tripId) return null;

  return (
    <div className="share-area">
      <button
        className="secondary share-trigger"
        type="button"
        aria-label="分享行程"
        title="分享行程"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <ShareIcon />
        <span>分享行程</span>
      </button>
      {open && pageActive && createPortal(
        <div className="share-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
        <div ref={dialogRef} className="share-dialog" role="dialog" aria-modal="true" aria-label="分享行程" tabIndex={-1}>
          <div className="share-dialog-head">
            <h2>分享行程</h2>
            <button
              type="button"
              className="share-dialog-close"
              onClick={() => setOpen(false)}
              aria-label="关闭分享面板"
            >
              <CloseIcon />
            </button>
          </div>
          {isOwner && (
            <section className="share-section">
              <h3>谁能看到</h3>
              <SegmentedControl<Visibility>
                options={[
                  { value: "private", label: "私密" },
                  { value: "link", label: "仅链接" },
                  { value: "public", label: "公开" },
                ]}
                value={visibility}
                onChange={(next) => void chooseVisibility(next)}
                label="行程可见性"
                className="share-visibility"
              />
              <p>
                {visibility === "private" && "只有你自己能打开。切换会撤销现有分享链接。"}
                {visibility === "link" && "拿到链接的人可以查看完整行程，不会出现在广场。"}
                {visibility === "public" && "广场所有人和持链接的人都能看；广场内容会自动脱敏。"}
              </p>
              {visibility === "link" && linkActive && !link && (
                <p>已有一条有效链接。出于安全这里不显示原文，需要重新发送时生成新链接。</p>
              )}
              {visibility === "public" && (
                <p>广场不展示精确出发日期和住宿详细地址，AI 对话也不会公开；只读链接页仍保留完整行程给同行者。</p>
              )}
              {visibilityBusy && <p role="status">正在更新可见性…</p>}
              {visibilityError && <div className="error" role="alert">{visibilityError}</div>}
              {visibilityNotice && <p className="share-status" role="status">{visibilityNotice}</p>}
            </section>
          )}
          {isOwner ? (
            <section className="share-section">
              <h3>只读分享</h3>
              <p>持有链接的人可以查看已保存的地点、活动、时间和路线，不含对话和待规划池。</p>
              {dirty && <p>请先保存当前修改，再生成分享链接。</p>}
              <div className="share-actions">
                <button className="primary" type="button" disabled={dirty || busy} onClick={create}>
                  {busy ? "处理中…" : link ? "生成新链接（旧链接失效）" : "生成链接"}
                </button>
                <button className="text-btn" type="button" disabled={busy} onClick={revoke}>
                  撤销所有链接
                </button>
                {link && (
                  <button className="text-btn" type="button" disabled={busy} onClick={revokeCurrentLink}>
                    撤销这条链接
                  </button>
                )}
              </div>
              {link && (
                <div className="share-link">
                  <span className="share-link-text" title={link}>{maskShareLink(link)}</span>
                  <button type="button" className="secondary" onClick={copyShareLink}>
                    复制
                  </button>
                </div>
              )}
              {error && <div className="error" role="alert">{error}</div>}
              {notice && <p role="status" className="share-status">{notice}</p>}
              <small>重新生成会立即撤销旧链接；链接仅能在可以访问本服务的设备打开。</small>
            </section>
          ) : (
            <section className="share-section">
              <h3>只读分享</h3>
              <p>分享链接由创建者管理。</p>
            </section>
          )}

          <section className="share-section">
            <h3>协作者</h3>
            <p>受邀成员可以一起编辑这份行程；只有创建者能生成邀请或移除成员。</p>
            {isOwner && (
              <div className="share-actions">
                <button className="secondary" type="button" disabled={inviteBusy} onClick={createInvite}>
                  {inviteBusy ? "生成中…" : "邀请协作者"}
                </button>
                <button
                  className="text-btn"
                  type="button"
                  disabled={inviteBusy || revokeInvitesBusy}
                  onClick={revokeInvites}
                >
                  {revokeInvitesBusy ? "撤销中…" : "撤销未使用邀请"}
                </button>
              </div>
            )}
            {inviteLink && (
              <div className="share-invite">
                <input
                  aria-label="邀请链接"
                  readOnly
                  value={inviteLink}
                  onFocus={(event) => event.currentTarget.select()}
                />
                <button type="button" className="secondary" onClick={copyInviteLink}>
                  复制
                </button>
              </div>
            )}
            {inviteLink && inviteValidity && (
              <p className="share-status">{inviteValidity}</p>
            )}
            {inviteError && <div className="error" role="alert">{inviteError}</div>}
            {inviteNotice && <p className="share-status" role="status">{inviteNotice}</p>}

            {membersBusy ? (
              <p className="share-status">正在读取成员…</p>
            ) : membersError ? (
              <div className="error" role="alert">{membersError}</div>
            ) : !members || members.length === 0 ? (
              <p className="share-status">还没有协作者。生成邀请链接后发给朋友。</p>
            ) : (
              <ul className="share-members">
                {members.map((member) => (
                  <li className="share-member" key={member.user_id}>
                    <span className="share-member-name">
                      {member.username}
                      <span className="share-member-role">{member.role === "edit" ? "可编辑" : member.role === "owner" ? "创建者" : member.role === "view" ? "只读" : member.role}</span>
                    </span>
                    {isOwner && member.role !== "owner" && (
                      <button
                        type="button"
                        className="share-member-remove"
                        disabled={removing === member.user_id}
                        aria-busy={removing === member.user_id}
                        aria-label={removing === member.user_id ? `正在移除协作者${member.username}` : `移除协作者${member.username}`}
                        title={`移除协作者${member.username}`}
                        onClick={() => removeMember(member)}
                      >
                        <UserMinusIcon size={20} />
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {membersNotice && <p className="share-status" role="status">{membersNotice}</p>}
          </section>

          {isOwner && !joinCodeHidden && (
            <section className="share-section">
              <h3>分享码</h3>
              <p>把分享码发给朋友，对方在「我的行程」页输入分享码即可加入，加入后可以和你一起实时编辑。</p>
              {joinCodeLoading && !joinCode ? (
                <p className="share-status" role="status">正在读取分享码…</p>
              ) : joinCode ? (
                <div className="share-actions">
                  <strong className={styles.joinCode}>{joinCode}</strong>
                  <Button variant="secondary" onClick={copyJoinCode}>复制</Button>
                  <Button variant="text" disabled={joinCodeBusy} onClick={rotateJoinCode}>重置</Button>
                  <Button variant="text" disabled={joinCodeBusy} onClick={disableJoinCode}>停用</Button>
                </div>
              ) : (
                <div className="share-actions">
                  <Button loading={joinCodeBusy} onClick={createJoinCode}>生成分享码</Button>
                </div>
              )}
              {joinCodeError && <div className="error" role="alert">{joinCodeError}</div>}
              {joinCodeNotice && <p className="share-status" role="status">{joinCodeNotice}</p>}
            </section>
          )}

          {!isOwner && (
            <section className="share-section">
              <h3>协作关系</h3>
              <p>你正在以协作者身份编辑这份行程，退出后需要重新接受邀请才能回来。</p>
              <div className="share-actions">
                <button type="button" className="text-btn" disabled={leaveBusy} onClick={leaveTrip}>
                  {leaveBusy ? "正在退出…" : "退出这个行程"}
                </button>
              </div>
              {leaveError && <div className="error" role="alert">{leaveError}</div>}
            </section>
          )}
        </div>
        </div>, document.body)}
    </div>
  );
}
