type StepperProps = {
  current: number
  labels: readonly string[]
}

export function Stepper({ current, labels }: StepperProps) {
  return (
    <nav aria-label="Progress" className="w-full">
      <ol className="flex flex-wrap items-center justify-center gap-2 sm:gap-3">
        {labels.map((label, i) => {
          const n = i + 1
          const done = n < current
          const active = n === current
          return (
            <li key={label} className="flex items-center gap-2 sm:gap-3">
              {i > 0 && (
                <div
                  className={`hidden h-px w-6 sm:block sm:w-10 ${done ? 'bg-accent/60' : 'bg-white/10'}`}
                  aria-hidden
                />
              )}
              <div
                className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium transition-colors sm:text-sm ${
                  active
                    ? 'bg-accent/20 text-accent ring-1 ring-accent/40'
                    : done
                      ? 'text-slate-300'
                      : 'text-slate-500'
                }`}
              >
                <span
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] ${
                    active
                      ? 'bg-accent text-slate-950'
                      : done
                        ? 'bg-white/15 text-slate-200'
                        : 'bg-white/5 text-slate-500'
                  }`}
                >
                  {done ? '✓' : n}
                </span>
                <span className="max-w-[5.5rem] truncate sm:max-w-none">{label}</span>
              </div>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
