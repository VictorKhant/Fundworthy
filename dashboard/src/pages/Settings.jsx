import { useCallback, useEffect, useRef, useState } from "react";
import { useConfirm } from "../components/Confirm";
import Icon from "../components/Icon";
import JoinOrg from "../components/JoinOrg";
import Organization, { Meter } from "../components/Organization";
import Spinner, { Busy } from "../components/Spinner";
import { api } from "../api";
import { authEnabled, orgDisplayName, signOutNow } from "../auth";

// The API key page.
//
// CLAUDE.md said "the user never sees a terminal, a repo, a config file, or an API key."
// The last of those has changed, deliberately: §11 Q6 asks who owns the key and the bill,
// and there is no honest answer that does not involve someone at the organisation holding
// it. What survives is the part that mattered — they handle it in one box, once, and
// never again. The three-step walkthrough is the rest of that promise: "go to
// console.anthropic.com" is not instructions to someone who has never been there.
//
// The box is write-only. Once saved, the key is encrypted on disk and no endpoint will
// return it; the page can only ever show the last four characters. That is why there is a
// "Check it still works" control — they can confirm the saved key is good without anyone
// having to read it back to them.

const STEPS = [
  <>
    Go to <strong>console.anthropic.com</strong> and sign up — like creating any online
    account.
  </>,
  <>
    Open <strong>API keys</strong>, press <strong>Create key</strong>, and copy the text
    that starts with <code>sk-ant-</code>.
  </>,
  <>Paste it below and press Save. Whoever's account it is pays the bill.</>,
];

function KeyPanel({ state, onChange, inputRef }) {
  const [dialog, ask] = useConfirm();
  const [key, setKey] = useState("");
  // Which of the three is running, not just "something is". They take visibly different
  // amounts of time — checking a key is a round trip to Anthropic — so the spinner has to
  // land on the button that is actually working.
  const [doing, setDoing] = useState(null); // "save" | "test" | "remove" | null
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const busy = doing !== null;

  async function save() {
    setDoing("save");
    setError(null);
    setResult(null);
    try {
      await api.settings.saveKey(key.trim());
      setKey("");
      setResult({ ok: true, message: "Saved. It is encrypted on this computer." });
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setDoing(null);
    }
  }

  async function test() {
    setDoing("test");
    setError(null);
    setResult(null);
    try {
      setResult(await api.settings.testKey(key.trim() || undefined));
    } catch (e) {
      setError(e.message);
    } finally {
      setDoing(null);
    }
  }

  async function remove() {
    const answer = await ask({
      icon: "bin",
      tone: "clay",
      title: "Remove the saved key?",
      points: [
        "Searches will stop running until you add one — Fundworthy has nothing to read "
          + "funders' pages with.",
        "Nothing you have already found is deleted.",
        "You can paste the same key back at any time.",
      ],
      confirmLabel: "Remove it",
    });
    if (!answer) return;
    setDoing("remove");
    try {
      await api.settings.deleteKey();
      setResult({ ok: true, message: "Removed." });
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setDoing(null);
    }
  }

  return (
    <section className="panel raised">
      {dialog}
      <h2>Your AI key</h2>
      <p className="settings-lede">
        The key is what pays for the reading and scoring — think of it as the researcher's
        bus fare. At this volume it costs a couple of dollars a month, and every search
        stops itself at the limit you set.
      </p>

      <ol className="steps">
        {STEPS.map((s, i) => (
          <li key={i}>
            <span className="step-n" aria-hidden="true">{i + 1}</span>
            <span>{s}</span>
          </li>
        ))}
      </ol>

      {/* Three states, not two. "Nothing saved here" and "nothing anywhere" look identical
          on this page but behave completely differently: with a .env on the machine the
          pipeline scores regardless, and a page that only said "no key saved" would flatly
          contradict what the next run then does. */}
      {state.has_api_key && (
        <div className="notice">
          A key is saved: <code>{state.api_key_hint}</code> — encrypted, and never shown in
          full to anyone.{" "}
          <Busy className="text notice-action" busy={doing === "test"}
                busyLabel="Checking" onClick={test} disabled={busy}>
            Check it still works
          </Busy>
        </div>
      )}

      {/* A local install only. On a deployed Fundworthy the environment key does not
          resolve for anybody, so every org saves its own here — see
          `app/secrets.py: resolve_api_key`. */}
      {!state.has_api_key && state.api_key_source === "environment" && (
        <div className="notice plain">
          <strong>No key is saved here</strong> — but this is a local install, and the
          researcher is using one (<code>{state.env_key_hint}</code>) from this machine's{" "}
          <code>.env</code>, so searches will still be scored. Saving a key here takes
          priority over it, and is the one to rely on.
        </div>
      )}

      {/* This is the state that stops the app working, so it says so. It used to read
          "the researcher can still find and filter pages, but it cannot read or score
          them", which describes a degraded mode that no longer exists: without a key a
          search is refused up front rather than crawling for ten minutes to produce
          nothing. */}
      {!state.key_available && (
        <div className="notice error">
          <strong>No key yet, so searches will not run.</strong> Fundworthy reads funders'
          pages with Claude and there is nothing here to read them with. Paste a key below
          and the Search button on <strong>This week</strong> comes back on.
        </div>
      )}

      <div className="keyrow">
        <label className="field">
          <span>{state.has_api_key ? "Replace it with a new key" : "Paste your key"}</span>
          <input
            ref={inputRef}
            type="password"
            value={key}
            autoComplete="off"
            placeholder="sk-ant-…"
            onChange={(e) => setKey(e.target.value)}
          />
        </label>
        <Busy className="primary" busy={doing === "save"} busyLabel="Saving"
              onClick={save} disabled={busy || key.trim().length < 8}>
          Save key
        </Busy>
        {/* Checking a key before trusting it is a real capability, not a duplicate of the
            link above: that one tests what is stored, this one tests what was just typed. */}
        {key.trim().length >= 8 && (
          <Busy busy={doing === "test"} busyLabel="Checking with Anthropic"
                onClick={test} disabled={busy}>
            Check it first
          </Busy>
        )}
        {state.has_api_key && (
          <Busy className="danger" busy={doing === "remove"} busyLabel="Removing"
                onClick={remove} disabled={busy}>
            Remove saved key
          </Busy>
        )}
      </div>

      {result && <div className={`notice ${result.ok ? "" : "error"}`}>{result.message}</div>}
      {error && <div className="notice error">{error}</div>}
    </section>
  );
}

// Which AI it uses.
//
// The model picker on This week offers whatever `state.model_choices` holds, and there
// was nowhere at all to change what that is — the per-stage half of R5 shipped and the
// provider half did not, which left "pick a model" as a control with no upstream.
//
// **Only Anthropic is live, and the other three say so rather than being absent.** That
// is the honest shape of it today: connecting one of them needs a provider column on the
// stored key, one adapter interface in `agent/score.py`, per-provider pricing and a
// `resolve_api_key` that returns which provider a key belongs to. None of that is built.
// A disabled card that names the thing is a signpost; leaving the card out entirely
// would make the picker's "add a provider under Settings" line point at nothing.
const PROVIDERS = [
  {
    key: "anthropic",
    name: "Anthropic",
    mark: "A",
    models: "Claude Haiku, Sonnet, Opus",
    live: true,
  },
  { key: "openai", name: "OpenAI", mark: "O", models: "GPT models" },
  { key: "deepseek", name: "DeepSeek", mark: "D", models: "DeepSeek models" },
  { key: "qwen", name: "Qwen", mark: "Q", models: "Qwen models" },
];

function Providers({ state, onGoKey }) {
  return (
    <section className="panel raised">
      <h2>Which AI it uses</h2>
      <p className="settings-lede">
        Connect a provider here and its models become choosable on the three boxes on{" "}
        <strong>This week</strong>. You can mix them — a cheap model for the quick read, a
        stronger one for scoring.
      </p>

      <div className="providers">
        {PROVIDERS.map((p) => {
          const connected = p.live && state.key_available;
          return (
            <div key={p.key}
                 className={`provider ${connected ? "on" : ""} ${p.live ? "" : "soon"}`}>
              <div className="provider-head">
                <span className="provider-mark" aria-hidden="true">{p.mark}</span>
                <span className="provider-name">{p.name}</span>
                {connected && (
                  <span className="provider-check" aria-hidden="true">
                    <Icon name="check" size={13} />
                  </span>
                )}
              </div>
              <p className="provider-models">
                {p.live ? p.models : "Not connected yet"}
              </p>
              {p.live ? (
                <button className="pill" onClick={onGoKey}>
                  {state.has_api_key ? "Replace key" : "Add a key"}
                </button>
              ) : (
                <button className="pill" disabled
                        title="Fundworthy only reads with Claude today">
                  Add a key
                </button>
              )}
            </div>
          );
        })}
      </div>

      <p className="muted small">
        Only Claude is connected today — the other three are what this panel is for once
        Fundworthy can read with them.
      </p>
    </section>
  );
}

function OrgPanel({ settings, onChange }) {
  const [draft, setDraft] = useState({
    org_name: settings.org_name || "",
    org_location: settings.org_location || "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setDraft({
      org_name: settings.org_name || "",
      org_location: settings.org_location || "",
    });
  }, [settings.org_name, settings.org_location]);

  const dirty =
    draft.org_name !== (settings.org_name || "") ||
    draft.org_location !== (settings.org_location || "");

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api.settings.save(draft);
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="panel raised">
      <h2>Name and city</h2>
      <p className="settings-lede">
        The name is used wherever Fundworthy refers to you. The city decides which
        researched lists are offered first on <strong>Discover funders</strong> — it
        never hides a grant from you.
      </p>

      <div className="knobs knobs-row">
        <label className="field">
          <span>Organization name</span>
          <input
            type="text"
            value={draft.org_name}
            placeholder="Your organization"
            onChange={(e) => setDraft({ ...draft, org_name: e.target.value })}
          />
        </label>
        {/* Not a filter. It used to feed a geographic reject that ran on the words of
            every page, which was the wrong instrument — where you can apply is decided
            by which funders you chose to search, not by pattern-matching prose. This
            now only picks which city's funder directory you are shown first. */}
        <label className="field">
          <span>Your city</span>
          <input
            type="text"
            value={draft.org_location}
            placeholder="San Diego, California"
            onChange={(e) => setDraft({ ...draft, org_location: e.target.value })}
          />
        </label>
        <Busy className="dark" busy={saving} busyLabel="Saving"
              onClick={save} disabled={!dirty}>
          Save
        </Busy>
      </div>

      {error && <div className="notice error">{error}</div>}
    </section>
  );
}

// Opting in to sharing the funders you added by hand.
//
// Off by default and asked for plainly. A funder list is not private — a name, a grants
// page and a sector — but "not private" is not the same as "ours to publish on their
// behalf", and an org that has never been asked has not agreed to anything.
//
// The copy is specific about what does and does not leave, because "share my funders"
// could reasonably be heard as "share my findings", which would be a very different and
// much worse thing.
function ShareFunders({ settings, onChange }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [mine, setMine] = useState(null);
  const on = Boolean(settings.share_funders);

  // What actually happened to the funders you offered.
  //
  // Without this the feature is a checkbox that does nothing observable. Ticking it
  // schedules a background fetch of each page, and a funder is only offered to anybody
  // once that has passed — so a page with an expired certificate, or a homepage with no
  // grant language, silently never appears and you have no way to find out. That is
  // exactly what happened the first time this was tested: added a foundation, looked on
  // another account, saw nothing, and nothing anywhere said why.
  const load = useCallback(async () => {
    try {
      const all = (await api.funders.list()).funders;
      setMine(all.filter((f) => f.added_by === "user"));
    } catch {
      setMine([]);
    }
  }, []);
  useEffect(() => { load(); }, [load, settings.share_funders]);

  async function toggle(next) {
    setSaving(true);
    setError(null);
    try {
      await api.settings.save({ share_funders: next });
      await onChange();
      // The checks run in a background thread, so the first look is usually too early.
      // One delayed refresh turns "nothing here" into the real answer without making
      // anybody press anything.
      setTimeout(load, 4000);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  const offered = (mine || []).filter((f) => f.check_ok === true);
  const rejected = (mine || []).filter((f) => f.check_ok === false);
  const waiting = (mine || []).filter((f) => f.check_ok === null
                                          || f.check_ok === undefined);

  return (
    <section className="panel">
      <h2>Helping other nonprofits</h2>
      <p className="settings-lede">
        Funders you add by hand are research somebody did. Sharing them puts the name and
        the grants page on other nonprofits' <strong>Discover funders</strong> page, so
        the next organization in your city does not start from nothing.
      </p>

      <label className="check">
        <input type="checkbox" checked={on} disabled={saving}
               onChange={(e) => toggle(e.target.checked)} />
        Share the funders I add with other nonprofits
      </label>

      <ul className="tut-sub">
        <li>
          Only funders <strong>you typed in</strong>. The researched lists are already
          available to everyone, so re-sharing a copy of one adds nothing.
        </li>
        <li>
          Only the name, the web address, the sector and your note.{" "}
          <strong>Never your findings, your programs, your spending or your name.</strong>
        </li>
        <li>
          Nothing appears until we have checked the page opens and looks like it is about
          grants. Untick this at any time and yours stop being offered.
        </li>
      </ul>

      {saving && <p className="loading-line"><Spinner label="Saving" />Saving…</p>}
      {error && <div className="notice error">{error}</div>}

      {on && mine !== null && (
        mine.length === 0 ? (
          <div className="notice plain">
            You have not added any funders by hand yet, so there is nothing to share.
            Funders that came from the researched lists do not count — everybody already
            has those. Add one on <strong>Discover funders</strong>.
          </div>
        ) : (
          <>
            <h3 className="sub">
              What you are offering — {offered.length} of {mine.length}
            </h3>
            <ul className="plain">
              {offered.map((f) => (
                <li key={f.id} className="member">
                  <span>✓ {f.name}</span>
                  <span className="muted small">{f.check_note}</span>
                </li>
              ))}
              {waiting.map((f) => (
                <li key={f.id} className="member">
                  <span>{f.name}</span>
                  <span className="muted small">Waiting to be checked…</span>
                </li>
              ))}
              {/* The one that matters. A funder that failed is not being offered to
                  anybody, and the reason is usually something the person can fix — a
                  homepage instead of a grants page, or a link with a typo in it. */}
              {rejected.map((f) => (
                <li key={f.id} className="member">
                  <span className="muted">{f.name} — not shared</span>
                  <span className="muted small">{f.check_note}</span>
                </li>
              ))}
            </ul>
            {rejected.length > 0 && (
              <p className="muted small">
                Fixing the web address on <strong>Discover funders</strong> makes us look
                again.
              </p>
            )}
          </>
        )
      )}
    </section>
  );
}

// The moderation queue. Only rendered for whoever `FUNDWORTHY_ADMIN_EMAILS` names — the
// parent `Settings` component is the one that finds this out (`reportsData`, fetched
// once below), so the "Reported funders" tab itself can stay hidden from anyone else
// rather than opening onto an empty or broken screen. The server checks again
// regardless; a hidden tab is not a permission.
//
// A report hides the funder from everybody the moment it is filed, before anyone looks.
// So the two actions here are "it really was bad" and "put it back", and the second one
// matters: without it a single objection would permanently remove a good funder, and
// one person's mistake would be indistinguishable from moderation. Grouped by FUNDER,
// not by report — two nonprofits can object to the same one independently, and
// resolving that is one decision, not two (`app/repo.py: all_reports`).
const REPORT_FILTERS = [
  ["open", "Waiting on you"],
  ["upheld", "Taken down"],
  ["dismissed", "Left up"],
];

function ReportedFundersTab({ data, onReload }) {
  const [filter, setFilter] = useState("open");
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const groups = data.reports || [];
  const counts = data.counts || { open: 0, upheld: 0, dismissed: 0 };
  const visible = groups.filter((g) => g.status === filter);

  async function resolve(g, uphold) {
    const key = `${g.funder_org}:${g.funder_id}`;
    setBusy(key);
    setError(null);
    try {
      await api.admin.resolve(g.funder_org, g.funder_id, uphold);
      await onReload();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <div className="report-stats">
        {REPORT_FILTERS.map(([key, label]) => (
          <div key={key} className="report-stat">
            <strong>{counts[key] || 0}</strong>
            <span>{label.toLowerCase()}</span>
          </div>
        ))}
      </div>

      <section className="panel raised">
        <div className="panel-head">
          <div>
            <h2>Reported funders</h2>
            <p className="settings-lede">
              A report hides the funder from everyone straight away. Nothing here is
              visible to other nonprofits while you decide.
            </p>
          </div>
          <span className="pill locked">Admin only</span>
        </div>

        <div className="report-filters">
          {REPORT_FILTERS.map(([key, label]) => (
            <button key={key} type="button"
                    className={`pill ${filter === key ? "dark" : ""}`}
                    onClick={() => setFilter(key)}>
              {label} · {counts[key] || 0}
            </button>
          ))}
        </div>

        {error && <div className="notice error">{error}</div>}

        {visible.length === 0 ? (
          <p className="muted small">Nothing here.</p>
        ) : (
          <ul className="plain report-list">
            {visible.map((g) => {
              const key = `${g.funder_org}:${g.funder_id}`;
              return (
                <li key={key} className="report-row">
                  <div className="report-row-main">
                    <strong>{g.name || "(funder since deleted)"}</strong>
                    {g.reason && <p className="report-reason">“{g.reason}”</p>}
                    <p className="muted small">
                      {g.url && (
                        <>
                          <a href={g.url} target="_blank" rel="noopener noreferrer">
                            {g.url.replace(/^https?:\/\//, "")}
                          </a>
                          {" · "}
                        </>
                      )}
                      reported by {g.reported_by_count} organization
                      {g.reported_by_count === 1 ? "" : "s"}
                      {g.created_at && ` · ${g.created_at.slice(0, 10)}`}
                    </p>
                  </div>
                  {g.status === "open" && (
                    <span className="row report-actions">
                      <Busy className="text danger" busy={busy === key}
                            busyLabel="Removing" onClick={() => resolve(g, true)}>
                        Take it down
                      </Busy>
                      <Busy className="text" busy={busy === key} busyLabel="Restoring"
                            onClick={() => resolve(g, false)}>
                        Leave it up
                      </Busy>
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        <p className="muted small">
          You are seeing this because your address is in FUNDWORTHY_ADMIN_EMAILS.
        </p>
      </section>
    </>
  );
}

// Closing your account, at the bottom, behind typing your own address.
//
// The confirm step is a typed email rather than an "Are you sure?" because this is not
// reversible and the two buttons of a browser confirm are three pixels apart. Typing the
// address is a few seconds that cannot be done by accident.
//
// What it does is spelled out rather than summarised, because the honest answer is
// asymmetric and people should not have to guess at the asymmetry: the findings and the
// key go, the funder list stays. That is deliberate — a funder is a name and a grants
// page, not private research, and the intent is to fold hand-added ones into the shared
// directory so the next nonprofit in that city does not start from nothing.
// "Join another organization" — the same invitation code, from an account that already
// has something in it.
//
// The old form only ever appeared on a completely empty account, which meant somebody
// already using Fundworthy could not redeem a code at all. That is the group most likely
// to be handed one: two nonprofits merging, or somebody moving jobs.
//
// It used to be a leave as much as a join — the same rules as closing an account, behind
// a confirm dialog naming what would be lost — because redeeming a code MOVED you.
// `db.redeem_invite` no longer moves anybody: it ADDS the org the code belongs to
// alongside the one you already have, and switches you into it. Nothing here can be
// lost, so there is nothing left to confirm.
function JoinAnotherOrg({ onChange }) {
  const [note, setNote] = useState(null);

  return (
    <section className="panel raised">
      <h2>Join another organization</h2>
      <p className="settings-lede">
        Got an invitation code from a colleague? Using it <strong>adds</strong> their
        organization to yours — nothing here moves or is deleted, and you switch between
        them from the bottom of the menu.
      </p>

      {note && <div className="notice">{note}</div>}
      <JoinOrg cta="Join them"
               onJoined={async () => {
                 setNote("You have joined that organization — switch to it from the "
                        + "bottom of the menu, next to your name.");
                 await onChange();
               }} />

      <p className="muted small">
        You will see their funders, programs and findings while you are in that
        organization, and their key pays for their searches. Yours stay exactly as they
        are.
      </p>
    </section>
  );
}

function DeleteAccount() {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [me, setMe] = useState(null);
  const [alone, setAlone] = useState(true);

  useEffect(() => {
    api.org.read()
      .then((org) => {
        const you = (org.members || []).find((m) => m.uid === org.you);
        setMe(you?.email || "");
        setAlone((org.members || []).length <= 1);
      })
      .catch(() => setMe(""));
  }, []);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      const out = await api.deleteAccount();
      // The data is gone either way. Whether the Firebase sign-in went with it is a
      // separate outcome, and saying "deleted" when the sign-in survived would be a
      // claim we cannot stand behind — so a stale session gets told what to do instead
      // of a cheerful goodbye.
      if (out.sign_in === "stale" || out.sign_in === "failed") {
        window.alert(
          "Your organization's data has been deleted.\n\n" +
          "Your sign-in could not be removed — Firebase refuses that when you last " +
          "signed in a while ago. Sign in once more and close your account again to " +
          "remove it, or leave it: it now opens onto an empty account with nothing in it."
        );
      }
      // Signing out is what actually ends the session in this browser. Without it the
      // page sits there holding a token for an account the server no longer knows,
      // 401ing on every request — which looks like a bug rather than a goodbye.
      await signOutNow();
      window.location.assign("/welcome");
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  // Nothing to delete on a local install: there are no accounts, and the data is a file
  // on this computer. Offering the button would be offering to do nothing.
  if (!authEnabled()) return null;

  return (
    <section className="panel danger-zone">
      <h2>Close your account</h2>
      {!open ? (
        <>
          <p className="settings-lede">
            Removes you from {alone ? "this organization" : "your organization"} and
            deletes your sign-in. {alone
              ? "Since you are the only person here, this organization's findings and "
                + "saved API key are deleted with it."
              : "Your colleagues keep working; nothing of theirs is touched."}
          </p>
          <button className="danger" onClick={() => setOpen(true)}>
            Close my account…
          </button>
        </>
      ) : (
        <>
          <p className="settings-lede">This cannot be undone. Here is exactly what happens:</p>
          <ul className="tut-sub">
            <li>You leave this organization.</li>
            {alone ? (
              <>
                <li>
                  <strong>Deleted:</strong> this month's findings, the search history, and
                  the saved Claude API key.
                </li>
                <li>
                  <strong>Kept:</strong> the funder list. Those are names and grants pages,
                  not private research — keeping them is how the next nonprofit in your
                  city starts with something rather than nothing.
                </li>
              </>
            ) : (
              <li>
                Your colleagues keep the funders, the findings and the key. Nothing of
                theirs is deleted.
              </li>
            )}
            <li>
              <strong>Your sign-in is removed</strong> so your email address is not kept
              here either. This does not touch your Google account — only the way you
              sign in to Fundworthy.
            </li>
            <li>
              Your Claude account and its billing are Anthropic's, not ours — close that
              separately if you want to.
            </li>
          </ul>

          <label className="field">
            <span>Type <strong>{me || "your email address"}</strong> to confirm</span>
            <input value={typed} autoComplete="off" placeholder={me || ""}
                   onChange={(e) => setTyped(e.target.value)} />
          </label>

          {error && <div className="notice error">{error}</div>}

          <div className="row">
            <Busy className="danger" busy={busy} busyLabel="Closing your account"
                  disabled={!me || typed.trim().toLowerCase() !== me.toLowerCase()}
                  onClick={remove}>
              Delete my account permanently
            </Busy>
            <button className="text" onClick={() => { setOpen(false); setTyped(""); }}
                    disabled={busy}>
              Cancel
            </button>
          </div>
        </>
      )}
    </section>
  );
}

// Four tabs where there used to be nine stacked panels. The page had grown one section
// at a time — a key, a provider picker, a budget meter, org name, members, invites,
// sharing, moderation, account deletion, a bug form — each addition reasonable on its
// own and, together, a page nobody could scan. The grouping below is not new
// information, only where it lives: money together, people together, the one
// irreversible thing on its own, and moderation — which is not for most people who open
// this page at all — behind a tab that only appears for whoever it is actually for.
const SETTINGS_TABS = [
  { id: "ai", label: "AI and spending" },
  { id: "organization", label: "Organization" },
  { id: "account", label: "Account" },
];

export default function Settings({ state, onChange, initialTab, onTabOpened }) {
  // Anthropic's "Add a key" on the provider panel is the same key box that is already on
  // this page, so it scrolls to it and puts the cursor in it rather than duplicating a
  // write-only field that no endpoint can read back.
  const keyBox = useRef(null);
  const goKey = () => {
    keyBox.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    keyBox.current?.focus({ preventScroll: true });
  };

  const [tab, setTab] = useState(initialTab || "ai");
  // null: not answered yet. false: this address is not an operator (or the install has
  // no admin at all) — the same 404-means-"not for you" signal `ReportQueue` always
  // used, just read one level up so the TAB can stay hidden, not only its contents.
  // An object: the real data, fetched once here rather than once per tab-switch.
  const [reportsData, setReportsData] = useState(null);

  const loadReports = useCallback(async () => {
    try {
      setReportsData(await api.admin.reports());
    } catch {
      setReportsData(false);
    }
  }, []);
  useEffect(() => { loadReports(); }, [loadReports]);

  // The org switcher's "Join another organization…" is the one caller that wants a
  // specific tab open. Every other entry to this page — the nav link, a reload — wants
  // the default, so this only fires when something upstream actually asked for a tab.
  useEffect(() => {
    if (!initialTab) return;
    setTab(initialTab);
    onTabOpened?.();
  }, [initialTab, onTabOpened]);

  const tabs = reportsData
    ? [...SETTINGS_TABS, { id: "reported", label: "Reported funders",
                           badge: reportsData.counts?.open || 0 }]
    : SETTINGS_TABS;

  return (
    <>
      <header>
        <h1>Settings</h1>
        <p className="muted small">
          Set up once. You shouldn't need to come back here often. Everything here
          belongs to <strong>{orgDisplayName(state.settings?.org_name)}</strong> — the
          key, the limit and the people.
        </p>
      </header>

      <nav className="settings-tabs" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`settings-tab ${tab === t.id ? "on" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            {t.badge > 0 && <span className="settings-tab-badge">{t.badge}</span>}
          </button>
        ))}
      </nav>

      {tab === "ai" && (
        <>
          <KeyPanel state={state} onChange={onChange} inputRef={keyBox} />
          <Providers state={state} onGoKey={goKey} />
          <section className="panel raised">
            <h2>What it spends</h2>
            {state.spend && <Meter spend={state.spend} onChange={onChange} />}
          </section>
        </>
      )}

      {tab === "organization" && (
        <>
          <OrgPanel settings={state.settings} onChange={onChange} />
          <Organization onChange={onChange} />
          {/* Adding a second organization, and switching between them from the sidebar
              — both real once joining stopped moving anybody. */}
          {authEnabled() && <JoinAnotherOrg onChange={onChange} />}
          <ShareFunders settings={state.settings} onChange={onChange} />
        </>
      )}

      {tab === "account" && <DeleteAccount />}

      {tab === "reported" && reportsData && (
        <ReportedFundersTab data={reportsData} onReload={loadReports} />
      )}
    </>
  );
}
