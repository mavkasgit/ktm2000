import React from "react"
import * as UI from "shared/ui"

type AnyProps = Record<string, unknown>

const CardImpl = (UI as AnyProps).Card as React.ComponentType<AnyProps> | undefined
const AlertImpl = (UI as AnyProps).Alert as React.ComponentType<AnyProps> | undefined
const BadgeImpl = (UI as AnyProps).Badge as React.ComponentType<AnyProps> | undefined

export function DenseCard(props: React.PropsWithChildren<{ title: string; right?: React.ReactNode }>) {
  if (CardImpl) {
    return (
      <CardImpl>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <strong>{props.title}</strong>
          {props.right}
        </div>
        {props.children}
      </CardImpl>
    )
  }

  return (
    <section style={{ border: "1px solid #d1d5db", borderRadius: 8, padding: 12, marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <strong>{props.title}</strong>
        {props.right}
      </div>
      {props.children}
    </section>
  )
}

export function InlineBadge({ children }: React.PropsWithChildren) {
  if (BadgeImpl) {
    return <BadgeImpl>{children}</BadgeImpl>
  }

  return (
    <span style={{ fontSize: 12, background: "#e5e7eb", borderRadius: 999, padding: "2px 8px" }}>
      {children}
    </span>
  )
}

export function ErrorBanner({ lines }: { lines: string[] }) {
  if (lines.length === 0) {
    return null
  }

  const body = (
    <div>
      <strong>Ошибки / предупреждения</strong>
      <ul style={{ marginTop: 6, marginBottom: 0, paddingLeft: 18 }}>
        {lines.map((line, idx) => (
          <li key={`${line}-${idx}`}>{line}</li>
        ))}
      </ul>
    </div>
  )

  if (AlertImpl) {
    return <AlertImpl variant="destructive">{body}</AlertImpl>
  }

  return (
    <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", color: "#991b1b", borderRadius: 8, padding: 10, marginBottom: 12 }}>
      {body}
    </div>
  )
}
