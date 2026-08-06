import { useCallback, useEffect, useMemo, useState } from "react";
import { api, money } from "../api";
import { authEnabled } from "../auth";
import JoinOrg from "./JoinOrg";
import Spinner, { Busy } from "./Spinner";

// The first-run walkthrough. It makes you do the steps rather than read about them.
//
// This replaced a checklist of paragraphs, and the difference is the point. A checklist
// tells a nonprofit administrator with no AI experience what to do and then leaves them
// on a dashboard full of controls to find it with. Reading "add your Claude key" and
// locating the Settings page are two different tasks, and the second is the one people
// abandon.
//
// So each step here contains the thing itself — the key box, the card drafter, the
// funder lists — and the button to continue does not light up until the step is actually
// done. Not as a discipline: because a walkthrough you can click past is a walkthrough
// that teaches you the buttons are decorative.
//
// **Every step's done-ness is read from the server, never from a flag we set.** If you
// finish half of this and close the tab, you come back to the step you stopped at. If
// you do a step somewhere else in the app, this notices. There is no separate record of
// your progress to drift out of sync with the account, because progress *is* the
// account.
//
// **Four steps, and the fourth is the one this was missing.** It used to end on the
// funder list as a fact to be told — "you already have 61, you do not need to do anything
// now" — which is true and useless. That list is the entire search space: Fundworthy
// reads the funders on it and nowhere else, so a nonprofit outside San Diego whose list
// is 58 San Diego foundations has an app that will politely find them nothing every week.
// It is now a step you act on, and the last step says out loud where the results come
// from, because nobody had ever been told.

const KEY_HELP = "https://console.claude.com/settings/keys";

function Step({ n, of, title, children, done, onNext, nextLabel = "Next" }) {
  return (
    <div className="tut-step">
      <p className="tut-count">Step {n} of {of}</p>
      <h2>{title}</h2>
      {children}
      <div className="tut-actions">
        <button className="dark" onClick={onNext} disabled={!done}>
          {done ? nextLabel : "Finish this step to continue"}
        </button>
      </div>
    </div>
  );
}

function KeyStep({ state, onChange, onJoined, ...rest }) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [joining, setJoining] = useState(false);

  async function save(event) {
    event.preventDefault();
    setBusy(true);
    setResult(null);
    try {
      // Tested before it is saved. Pasting a key that does not work and finding out a
      // week later, when the search returns nothing, is the worst version of this.
      const check = await api.settings.testKey(key.trim());
      if (!check.ok) {
        setResult(check.message);
        return;
      }
      await api.settings.saveKey(key.trim());
      setKey("");
      await onChange();
    } catch (e) {
      setResult(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Step {...rest} done={Boolean(state.key_available)}>
      {/* Asked before anything else, because "yes" makes the rest of the walkthrough
          unnecessary — you inherit a colleague's funders, cards and key rather than
          building your own. Asking afterwards would be asking somebody to throw away
          the work they just did. It used to be a separate card floating above the
          dashboard, only ever shown on a completely empty account. */}
      {authEnabled() && !state.key_available && (
        <div className="tut-join">
          {joining ? (
            <>
              <p className="small">
                Enter the code your colleague sent you. You will share their funders,
                programs and findings, and can skip the rest of this setup.
              </p>
              <JoinOrg onJoined={onJoined} />
              <button className="text small" onClick={() => setJoining(false)}>
                I don't have a code
              </button>
            </>
          ) : (
            <p className="small">
              Is someone at your organization already using Fundworthy?{" "}
              <button className="text" onClick={() => setJoining(true)}>
                Enter their invitation code
              </button>{" "}
              instead of setting this up again.
            </p>
          )}
        </div>
      )}

      <p>
        Fundworthy reads funders' websites using Claude, and it uses <strong>your</strong>{" "}
        key — so your searches are billed to you and nobody else can see them. A weekly
        search costs about a dollar.
      </p>
      {state.key_available ? (
        <p className="tut-ok">
          ✓ Your key is saved and working. Fundworthy can read pages for you.
        </p>
      ) : (
        <>
          <ol className="tut-sub">
            <li>
              Open <a href={KEY_HELP} target="_blank" rel="noreferrer">
                console.claude.com
              </a> and sign in or create an account.
            </li>
            <li>Add a payment method, then create an API key and copy it.</li>
            <li>
              While you are there, set a monthly spending limit. That one is enforced by
              Anthropic, so it holds even if something here goes wrong.
            </li>
          </ol>
          <form onSubmit={save} className="tut-form">
            <input
              type="password"
              value={key}
              placeholder="sk-ant-…"
              autoComplete="off"
              onChange={(e) => setKey(e.target.value)}
            />
            <Busy type="submit" busy={busy} busyLabel="Checking your key"
                  disabled={key.trim().length < 8}>
              Check and save
            </Busy>
          </form>
          {result && <div className="notice error">{result}</div>}
          <p className="muted small">
            It is encrypted before it is stored, and there is no page in Fundworthy —
            including this one — that can show it back to you.
          </p>
        </>
      )}
    </Step>
  );
}

function ProgramStep({ state, onChange, ...rest }) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState(null);
  const active = (state.programs || []).filter((p) => p.active);

  async function drafted(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setDraft((await api.programs.draft(url.trim())).draft);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function keep() {
    setSaving(true);
    try {
      await api.programs.create({ ...draft, active: true, reviewed_by_human: true });
      setDraft(null);
      setUrl("");
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Step {...rest} done={active.length > 0}>
      <p>
        Fundworthy needs to know what you do, so it can tell which grants are worth your
        time. You do not have to write anything: paste a link to a page on your own
        website and it will draft the card for you to correct.
      </p>

      {active.length > 0 && (
        <p className="tut-ok">
          ✓ {active.length} program{active.length === 1 ? "" : "s"} ready:{" "}
          {active.map((p) => p.name).join(", ")}
        </p>
      )}

      {!draft ? (
        <form onSubmit={drafted} className="tut-form">
          <input
            type="url"
            value={url}
            placeholder="https://your-organization.org/programs/…"
            onChange={(e) => setUrl(e.target.value)}
          />
          <Busy type="submit" busy={busy} busyLabel="Reading the page"
                disabled={!url.trim()}>
            Read this page
          </Busy>
        </form>
      ) : (
        <div className="tut-draft">
          <p className="muted small">
            A draft, not a decision — read it and change anything that is wrong.
          </p>
          <label className="field">
            <span>Program name</span>
            <input
              value={draft.name || ""}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </label>
          <label className="field">
            <span>What it does</span>
            <textarea
              rows={3}
              value={draft.summary || ""}
              onChange={(e) => setDraft({ ...draft, summary: e.target.value })}
            />
          </label>
          <div className="row">
            <Busy className="dark" busy={saving} busyLabel="Saving"
                  onClick={keep} disabled={!draft.name}>
              Looks right — save it
            </Busy>
            <button className="text" onClick={() => setDraft(null)} disabled={saving}>
              Start again
            </button>
          </div>
        </div>
      )}

      {busy && (
        <p className="loading-line">
          <Spinner label="Reading the page" />
          Reading your page and writing the card. This takes a few seconds.
        </p>
      )}

      {error && <div className="notice error">{error}</div>}
      {!state.key_available && (
        <p className="muted small">
          Reading a page uses your Claude key, so finish step 1 first.
        </p>
      )}
    </Step>
  );
}

// Step 3. The funder list, as something you do rather than something you are told.
//
// The version this replaces said "you already have 61 — you do not need to do anything
// now", which was accurate and left the most important fact about the product unsaid:
// **this list is the whole search.** Fundworthy reads the funders on it and nowhere
// else. Someone in Chicago who is never told that has an app that finds them nothing,
// weekly, for a reason they have no way to guess.
function FunderStep({ state, onChange, ...rest }) {
  const [lists, setLists] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const count = (state.funders || []).filter((f) => f.active).length;

  const load = useCallback(async () => {
    try {
      setLists((await api.directory.read()).lists);
    } catch (e) {
      setError(e.message);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function add(key) {
    setBusy(key);
    setError(null);
    try {
      await api.directory.import(key);
      await load();
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Step {...rest} done={count > 0}>
      <p>
        <strong>This list is the search.</strong> Every week Fundworthy reads the funders
        on it, and only those — it does not search the open web. So the list is worth five
        minutes now, and you can change it any time on <strong>Discover funders</strong>.
      </p>

      {count > 0 ? (
        <p className="tut-ok">
          ✓ {count} funder{count === 1 ? "" : "s"} will be checked for you each week.
        </p>
      ) : (
        <div className="notice error">
          Your list is empty, so a search would read nothing at all. Add at least one
          list below.
        </div>
      )}

      {error && <div className="notice error">{error}</div>}
      {!lists && (
        <p className="loading-line">
          <Spinner label="Loading the researched lists" />
          Loading the lists we have researched…
        </p>
      )}

      <div className="directory">
        {(lists || []).map((l) => (
          <div key={l.key} className="directory-row">
            <div>
              <strong>{l.name}</strong>{" "}
              <span className="muted small">
                {l.count} {l.count === 1 ? "source" : "funders"}
              </span>
              <p className="muted small">{l.description}</p>
            </div>
            {l.imported >= l.count ? (
              <span className="muted small">On your list</span>
            ) : (
              <Busy className="secondary" busy={busy === l.key} busyLabel="Adding"
                    onClick={() => add(l.key)}>
                {l.imported ? `Add the other ${l.count - l.imported}` : "Add to my list"}
              </Busy>
            )}
          </div>
        ))}
      </div>

      <p className="muted small">
        Not near San Diego? Add the federal and state lists here, then take the rest off
        on Discover funders — and add your own local funders there, one at a time. Taking
        a funder off costs you nothing every week afterwards: it is never fetched, never
        read, never scored.
      </p>
    </Step>
  );
}

// Step 4, and the only optional one. Skipping is a real answer, so the button says so
// rather than pretending everybody wants this.
//
// The weekly search is **off** until someone ticks it here. It used to be on for every
// new account, at Wednesday 11pm — which was the pilot organisation's answer to a
// question no other org had been asked, and it meant an unattended job spending a
// nonprofit's own Anthropic credit on a schedule they never chose. A default that spends
// somebody's money has to be opted into.
function ScheduleStep({ state, onChange, ...rest }) {
  const s = state.settings || {};
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const on = Boolean(s.schedule_enabled);

  async function write(changes) {
    setSaving(true);
    setError(null);
    try {
      await api.settings.save(changes);
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Step {...rest} done nextLabel={on ? "Next" : "Skip this — I'll search by hand"}>
      <p>
        Fundworthy can run your search on its own, once a week, and have the results
        waiting when you next open it. It uses your Claude key when it does, so this is
        entirely your call — <strong>it is off unless you turn it on</strong>.
      </p>
      <p className="muted small">
        Either way the <strong>Search again now</strong> button always works. Skipping
        here does not switch anything off.
      </p>

      <label className="check">
        <input
          type="checkbox"
          checked={on}
          disabled={saving}
          onChange={(e) => write({ schedule_enabled: e.target.checked })}
        />
        Search automatically every week
      </label>

      {on && (
        <div className="schedule">
          <span className="muted small">Every</span>
          <select value={s.schedule_day} disabled={saving}
                  onChange={(e) => write({ schedule_day: e.target.value })}>
            {["monday", "tuesday", "wednesday", "thursday", "friday",
              "saturday", "sunday"].map((d) => (
              <option key={d} value={d}>{d[0].toUpperCase() + d.slice(1)}</option>
            ))}
          </select>
          <span className="muted small">at</span>
          <select value={String(s.schedule_hour)} disabled={saving}
                  onChange={(e) => write({ schedule_hour: Number(e.target.value) })}>
            {Array.from({ length: 24 }, (_, h) => (
              <option key={h} value={h}>
                {h === 0 ? "12 midnight" : h < 12 ? `${h} am`
                  : h === 12 ? "12 noon" : `${h - 12} pm`}
              </option>
            ))}
          </select>
          <select value={s.schedule_timezone} disabled={saving}
                  onChange={(e) => write({ schedule_timezone: e.target.value })}>
            {[
              ["America/Los_Angeles", "Pacific"],
              ["America/Denver", "Mountain"],
              ["America/Chicago", "Central"],
              ["America/New_York", "Eastern"],
              ["America/Anchorage", "Alaska"],
              ["Pacific/Honolulu", "Hawaii"],
            ].map(([tz, label]) => <option key={tz} value={tz}>{label}</option>)}
          </select>
          <p className="muted small">
            Pick the evening before you want to read them. If the server is down at that
            hour the search runs as soon as it is back — you get the week's search either
            way, and never two of them.
          </p>
        </div>
      )}

      {saving && (
        <p className="loading-line"><Spinner label="Saving" />Saving…</p>
      )}
      {error && <div className="notice error">{error}</div>}
      <p className="muted small">
        You can change this any time under "Adjust search settings" on This week.
      </p>
    </Step>
  );
}

// Step 5. Where the results come from, said once, plainly, before the first search.
//
// It is the only step with nothing to do, and it earns its place: everything it says was
// previously discoverable only by running a search and reasoning backwards from what came
// out. A short list is the product working correctly, and somebody who does not know that
// reads their first Thursday as a failure.
function ReadyStep({ state, ...rest }) {
  const funders = (state.funders || []).filter((f) => f.active).length;
  const programs = (state.programs || []).filter((p) => p.active).length;
  const floor = money(state.settings?.min_award);
  // Stored lowercase ("wednesday") because the scheduler matches on it; capitalised here
  // because it is being read in a sentence, not parsed.
  //
  // Only spoken aloud if they actually chose it in the previous step. This line used to
  // read "It runs once a week, on Wednesday" to every new account — stating a schedule
  // nobody had set as though it were a fact about their account, when in truth nothing
  // was scheduled at all and Wednesday was just the value the column shipped with.
  const scheduled = Boolean(state.settings?.schedule_enabled);
  const stored = state.settings?.schedule_day || "";
  const day = stored ? stored[0].toUpperCase() + stored.slice(1) : "";

  return (
    <Step {...rest} done nextLabel="Take me to my dashboard">
      <p>You are set up. Here is what happens now, so nothing is a surprise.</p>

      <ul className="tut-sub">
        <li>
          <strong>It reads your {funders} funder{funders === 1 ? "" : "s"}</strong> —
          those pages and nowhere else — and matches what it finds against your{" "}
          {programs} ticked program{programs === 1 ? "" : "s"}.
        </li>
        <li>
          {scheduled ? (
            <>
              <strong>It searches on its own every {day}</strong>, and you can press
              "Search again now" whenever you like as well.
            </>
          ) : (
            <>
              <strong>It searches when you press "Search again now"</strong> — nothing
              runs on its own. You can switch on a weekly search, and pick the day and
              time, any time under "Adjust search settings".
            </>
          )}
        </li>
        <li>
          <strong>Expect a short list.</strong> Anything under {floor} is dropped before
          it costs you anything, because an application takes hours and a small grant does
          not repay them. Six results, all worth applying for, is a good week.
        </li>
        <li>
          <strong>It stops itself.</strong> Each search has a hard spending limit, and it
          stops rather than going over. You can turn the whole thing off from the
          dashboard.
        </li>
        <li>
          <strong>It never guesses.</strong> If a funder's page does not state an amount
          or a deadline, you get "not stated" and a link, not a number somebody made up.
        </li>
      </ul>
    </Step>
  );
}

export default function Tutorial({ state, onChange, onDone }) {
  const steps = useMemo(() => [
    { key: "key", Component: KeyStep, title: "Add your Claude key" },
    { key: "program", Component: ProgramStep, title: "Describe what you do" },
    { key: "funders", Component: FunderStep, title: "Choose who it watches" },
    { key: "schedule", Component: ScheduleStep, title: "Search on its own? (optional)" },
    { key: "ready", Component: ReadyStep, title: "How your search works" },
  ], []);

  // Open on the first unfinished step rather than always at one. Someone who saved a key
  // and closed the tab should not be walked through saving it again.
  const doneness = [
    Boolean(state.key_available),
    (state.programs || []).some((p) => p.active),
    (state.funders || []).some((f) => f.active),
    // The schedule step is optional, so it is never "already done" — landing on it and
    // pressing Skip is the expected path, not a step to be jumped over.
    false,
    false,          // the last step is a read, so it is never "already done" either
  ];
  const firstUnfinished = doneness.findIndex((d) => !d);
  const [at, setAt] = useState(firstUnfinished === -1 ? 0 : firstUnfinished);

  const { Component, title } = steps[at];
  const last = at === steps.length - 1;

  return (
    <div className="tutorial">
      {/* The rail is **progress**, not a scoreboard of the four `doneness` flags.
          Drawing the flags directly looked broken, and on a brand-new account it looked
          broken immediately: every org is seeded with funders, so step 3 was satisfied
          before anyone had done anything, and the rail opened as
          grey · grey · GREEN · grey — a filled segment sitting after two empty ones,
          which reads as a rendering fault rather than as information.

          Those flags are still exactly right for deciding which step to open on and when
          "Next" lights up; they are just not a sequence, and a four-segment bar is only
          ever read as one. So: passed, here, not yet — which is also the only reading
          that can agree with the "Step 1 of 4" printed underneath it. */}
      <div className="tut-rail" aria-hidden="true">
        {steps.map((s, i) => (
          <span key={s.key}
                className={`tut-pip ${i === at ? "at" : ""} ${i < at ? "done" : ""}`} />
        ))}
      </div>

      <Component
        state={state}
        onChange={onChange}
        n={at + 1}
        of={steps.length}
        title={title}
        onNext={() => (last ? onDone() : setAt(at + 1))}
        // Joining a colleague's org hands you a configured one — their key, their
        // funders, their program cards. Walking somebody through setting all three up
        // immediately afterwards would be asking them to redo work that is already done.
        //
        // So: if the org they landed in has finished onboarding, close the walkthrough
        // outright. If it has not — a colleague invited them into an org still being set
        // up — the remaining steps are real, so refresh and let the step logic reopen on
        // whichever one is genuinely unfinished.
        onJoined={async () => {
          const fresh = await onChange();
          if (fresh?.onboarding_done) {
            onDone();
          } else {
            setAt(steps.length - 1);
          }
        }}
      />

      {at > 0 && (
        <button className="text tut-back" onClick={() => setAt(at - 1)}>
          Back
        </button>
      )}
    </div>
  );
}
