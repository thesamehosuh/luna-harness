import icon from "../../../luna/assets/ui/luna-mark.svg";

/** The harness mark, shared with favicons and generated native app icons. */
export function LunaMark({ className }: { className?: string }) {
  return (
    <img src={icon} alt="" aria-hidden="true" className={className} />
  );
}
