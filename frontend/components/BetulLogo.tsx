export function BetulLogo({ size = "md" }: { size?: "sm" | "md" }) {
  const mark = size === "sm" ? "h-8 w-8" : "h-12 w-12";
  const title = size === "sm" ? "text-sm" : "text-xl";
  return (
    <div className="flex items-center gap-2.5">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/kiosk/betul-logo.svg" alt="" className={`${mark} shrink-0`} />
      <div className="flex flex-col leading-tight text-left">
        <span className={`${title} font-extrabold text-orange-600`}>बैतूल जन सुनवाई</span>
        {size === "md" && (
          <span className="text-xs font-bold text-orange-500 tracking-widest">
            ZILA PRASHASAN BETUL
          </span>
        )}
      </div>
    </div>
  );
}
