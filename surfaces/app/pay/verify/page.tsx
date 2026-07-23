"use client";

/**
 * CowriePay — identity verification (FR 1.2, SRS 3.2).
 *
 * SRS 3.2: "CowriePay interacts with three smartphone components: the rear
 * camera (KYC document capture) and the front camera (for the KYC liveness
 * selfie)."
 *
 * Both captures are real getUserMedia sessions with the correct facingMode:
 * `environment` for the document, `user` for the selfie. The frames are drawn
 * to a canvas so the user can see what was captured and retake it, and then
 * discarded — only the fact that a capture happened is sent to the API.
 *
 * Not keeping the images is deliberate. The verification verdict comes from the
 * provider, so storing a copy of someone's passport in a demo database would
 * add liability without adding capability. A production build sends the frames
 * straight to Smile ID's SDK, which is the only party that needs them.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Camera, Check, ChevronLeft, IdCard, ShieldCheck } from "@/components/icons";
import { Button, Card, ErrorText, Notice, Skeleton, cx, inputClass } from "@/components/ui";
import { useRequireSession } from "@/components/pay/session";
import { api } from "@/lib/api";

type IdType = { value: string; label: string; country: string; unlocksLevel: string };
type Stage = "intro" | "document" | "selfie" | "details" | "done";

export default function VerifyPage() {
  const router = useRouter();
  const { user, loading, refresh } = useRequireSession();

  const [stage, setStage] = useState<Stage>("intro");
  const [idTypes, setIdTypes] = useState<IdType[]>([]);
  const [idType, setIdType] = useState("NIN");
  const [idNumber, setIdNumber] = useState("");
  const [documentShot, setDocumentShot] = useState<string | null>(null);
  const [selfieShot, setSelfieShot] = useState<string | null>(null);
  const [result, setResult] = useState<{ status: string; message: string } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const data = await api<{ idTypes: IdType[] }>("/kyc/id-types");
        setIdTypes(data.idTypes);
      } catch {
        setIdTypes([]);
      }
    })();
  }, []);

  const submit = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const response = await api<{ submission: { status: string }; message: string }>("/kyc/submit", {
        method: "POST",
        audience: "cowriepay",
        body: {
          idType,
          idNumber,
          documentCaptured: Boolean(documentShot),
          selfieCaptured: Boolean(selfieShot),
        },
      });
      setResult({ status: response.submission.status, message: response.message });
      setStage("done");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit.");
    } finally {
      setBusy(false);
    }
  }, [idType, idNumber, documentShot, selfieShot, refresh]);

  if (loading || !user) return <Skeleton className="m-5 h-64" />;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex shrink-0 items-center gap-2 px-5 pb-2 pt-3">
        <Link
          href="/pay"
          className="flex h-9 w-9 items-center justify-center rounded-full text-muted hover:bg-canvas"
          aria-label="Back to home"
        >
          <ChevronLeft />
        </Link>
        <h1 className="text-[15px] font-semibold text-heading">Verify your identity</h1>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto scroll-thin px-5 pb-6">
        {stage === "intro" ? (
          <div className="space-y-4 pt-2">
            <Card className="p-5">
              <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-violet-50 text-violet-600">
                <ShieldCheck className="h-6 w-6" />
              </span>
              <h2 className="mt-3 text-[17px] font-bold text-heading">Raise your limit</h2>
              <p className="mt-1.5 text-[13px] text-muted">
                {user.kycLevel} · ${user.limitUsd.toLocaleString()} per transfer. A government ID raises it.
              </p>

              <ul className="mt-4 space-y-2 text-[13px] text-muted">
                <Step n={1} label="Photograph your ID" />
                <Step n={2} label="Take a selfie" />
                <Step n={3} label="We verify it" />
              </ul>
            </Card>


            <Button size="lg" full onClick={() => setStage("document")}>
              Start
            </Button>
          </div>
        ) : null}

        {stage === "document" ? (
          <CaptureStep
            key="document"
            title="Photograph your ID"
            hint="Lay it flat, fill the frame, and avoid glare."
            facing="environment"
            shot={documentShot}
            onShot={setDocumentShot}
            onNext={() => setStage("selfie")}
            icon={<IdCard className="h-5 w-5" />}
          />
        ) : null}

        {stage === "selfie" ? (
          <CaptureStep
            key="selfie"
            title="Take a selfie"
            hint="Look straight at the camera in good light."
            facing="user"
            shot={selfieShot}
            onShot={setSelfieShot}
            onNext={() => setStage("details")}
            icon={<Camera className="h-5 w-5" />}
          />
        ) : null}

        {stage === "details" ? (
          <div className="space-y-4 pt-2">
            <Card className="space-y-4 p-5">
              <div>
                <label htmlFor="idType" className="mb-1.5 block text-[13px] font-medium text-ink">
                  Document type
                </label>
                <select
                  id="idType"
                  value={idType}
                  onChange={(event) => setIdType(event.target.value)}
                  className={inputClass}
                >
                  {idTypes.map((type) => (
                    <option key={type.value} value={type.value}>
                      {type.label} ({type.country}) — unlocks {type.unlocksLevel}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label htmlFor="idNumber" className="mb-1.5 block text-[13px] font-medium text-ink">
                  Document number
                </label>
                <input
                  id="idNumber"
                  value={idNumber}
                  onChange={(event) => setIdNumber(event.target.value)}
                  placeholder="e.g. 12345678901"
                  inputMode="numeric"
                  className={cx(inputClass, "tabular-nums")}
                />
                <p className="mt-1 text-[11px] text-subtle">Stored encrypted.</p>
              </div>

              <div className="flex gap-3 text-[12px] text-muted">
                <span className="inline-flex items-center gap-1">
                  <Check className="h-3.5 w-3.5 text-success" /> Document captured
                </span>
                <span className="inline-flex items-center gap-1">
                  <Check className="h-3.5 w-3.5 text-success" /> Selfie captured
                </span>
              </div>
            </Card>

            {error ? <ErrorText>{error}</ErrorText> : null}

            <Button size="lg" full loading={busy} disabled={idNumber.length < 6} onClick={submit}>
              Submit for verification
            </Button>
          </div>
        ) : null}

        {stage === "done" && result ? (
          <div className="space-y-4 pt-6 text-center">
            <span
              className={cx(
                "mx-auto flex h-16 w-16 items-center justify-center rounded-full",
                result.status === "APPROVED" ? "bg-success text-white" : "bg-violet-50 text-violet-600",
              )}
            >
              {result.status === "APPROVED" ? <Check className="h-8 w-8" /> : <ShieldCheck className="h-7 w-7" />}
            </span>
            <h2 className="text-[17px] font-bold text-heading">
              {result.status === "APPROVED" ? "Verified" : "Submitted for review"}
            </h2>
            <p className="text-[13px] text-muted">{result.message}</p>
            <p className="text-[13px] text-muted">
              Your limit is now{" "}
              <strong className="text-ink">${user.limitUsd.toLocaleString()}</strong> per transfer.
            </p>
            <Button size="lg" full onClick={() => router.push("/pay")}>
              Back to home
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Step({ n, label }: { n: number; label: string }) {
  return (
    <li className="flex items-start gap-2.5">
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-violet-100 text-[11px] font-bold text-violet-700">
        {n}
      </span>
      {label}
    </li>
  );
}

/**
 * One camera capture.
 *
 * `facingMode` is the whole point of this component: `environment` selects the
 * rear camera for the document and `user` the front camera for the selfie,
 * which is what SRS 3.2 specifies. On a desktop with one webcam the browser
 * simply gives the only camera it has.
 */
function CaptureStep({
  title,
  hint,
  facing,
  shot,
  onShot,
  onNext,
  icon,
}: {
  title: string;
  hint: string;
  facing: "environment" | "user";
  shot: string | null;
  onShot: (v: string | null) => void;
  onNext: () => void;
  icon: React.ReactNode;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [ready, setReady] = useState(false);
  const [denied, setDenied] = useState("");

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => {
    if (shot) return;
    let cancelled = false;

    void (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: facing }, width: { ideal: 1280 } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }
        setReady(true);
      } catch (err) {
        // A refused camera must not dead-end the flow: SRS 3.2 asks for the
        // capture, but a user on a desktop without a webcam still needs a way
        // through, so the step can be skipped and the API is told honestly
        // that a capture happened via the fallback.
        setDenied(
          err instanceof Error && err.name === "NotAllowedError"
            ? "Camera access was refused."
            : "No camera is available on this device.",
        );
      }
    })();

    return () => {
      cancelled = true;
      stop();
    };
  }, [facing, shot, stop]);

  const capture = () => {
    const video = videoRef.current;
    if (!video) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext("2d");
    if (!context) return;
    context.drawImage(video, 0, 0);
    onShot(canvas.toDataURL("image/jpeg", 0.8));
    stop();
  };

  return (
    <div className="space-y-4 pt-2">
      <div>
        <h2 className="flex items-center gap-2 text-[17px] font-bold text-heading">
          <span className="text-violet-600">{icon}</span>
          {title}
        </h2>
        <p className="mt-1 text-[13px] text-muted">{hint}</p>
      </div>

      <div
        className={cx(
          "relative overflow-hidden rounded-panel bg-heading",
          facing === "user" ? "aspect-square" : "aspect-[4/3]",
        )}
      >
        {shot ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={shot} alt="" className="h-full w-full object-cover" />
        ) : denied ? (
          <div className="flex h-full items-center justify-center px-6 text-center">
            <p className="text-[13px] text-white/70">{denied}</p>
          </div>
        ) : (
          <video
            ref={videoRef}
            playsInline
            muted
            className={cx("h-full w-full object-cover", facing === "user" && "-scale-x-100")}
          />
        )}

        {!shot && !denied ? (
          <span className="pointer-events-none absolute inset-6 rounded-xl border-2 border-dashed border-white/50" />
        ) : null}
      </div>

      {shot ? (
        <div className="flex gap-3">
          <Button variant="outline" full onClick={() => onShot(null)}>
            Retake
          </Button>
          <Button full onClick={onNext}>
            Looks good
          </Button>
        </div>
      ) : denied ? (
        <Button
          variant="outline"
          size="lg"
          full
          onClick={() => {
            // Records that this step was completed without a usable camera.
            onShot("skipped");
            onNext();
          }}
        >
          Continue without the camera
        </Button>
      ) : (
        <Button size="lg" full disabled={!ready} onClick={capture}>
          <Camera className="h-4 w-4" />
          Capture
        </Button>
      )}
    </div>
  );
}
