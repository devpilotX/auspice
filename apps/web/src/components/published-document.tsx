/**
 * Renders a parsed published document through the design system primitives.
 *
 * No stylesheet override and no `dangerouslySetInnerHTML`. The parser hands back structured nodes and each
 * one maps to a token, which is why a methodology page looks like the rest of the product rather than like
 * a README someone pasted into a div.
 */

import type { ReactNode } from "react";

import { Panel, Rule } from "@/components/primitives";
import type { Block, Inline } from "@/lib/published-doc";

function Inlines({ nodes }: { nodes: Inline[] }) {
  return (
    <>
      {nodes.map((node, index) => {
        if (node.kind === "strong") {
          return (
            <strong key={index} style={{ fontWeight: 500, color: "var(--text-primary)" }}>
              {node.value}
            </strong>
          );
        }
        if (node.kind === "code") {
          return (
            <code
              key={index}
              className="font-mono"
              style={{
                fontSize: "var(--text-tiny)",
                backgroundColor: "var(--bg-tag)",
                border: "1px solid var(--line-hairline)",
                borderRadius: 2,
                padding: "0.05em 0.3em",
              }}
            >
              {node.value}
            </code>
          );
        }
        return <span key={index}>{node.value}</span>;
      })}
    </>
  );
}

const HEADING_STYLE = {
  1: { fontSize: "var(--text-title)", marginTop: 0 },
  2: { fontSize: "var(--text-heading)", marginTop: "2.5rem" },
  3: { fontSize: "var(--text-body)", marginTop: "1.75rem" },
} as const;

function Heading({ level, children }: { level: 1 | 2 | 3; children: ReactNode }) {
  const Tag = level === 1 ? "h1" : level === 2 ? "h2" : "h3";
  const style = HEADING_STYLE[level];
  return (
    <Tag
      style={{
        fontFamily: level === 3 ? "var(--font-sans)" : "var(--font-serif)",
        fontSize: style.fontSize,
        marginTop: style.marginTop,
        marginBottom: "0.75rem",
        color: "var(--text-primary)",
        fontWeight: level === 3 ? 500 : 400,
      }}
    >
      {children}
    </Tag>
  );
}

export function PublishedDocument({ blocks }: { blocks: Block[] }) {
  return (
    <article className="max-w-2xl">
      {blocks.map((block, index) => {
        if (block.kind === "heading") {
          return (
            <div key={index}>
              <Heading level={block.level}>
                <Inlines nodes={block.text} />
              </Heading>
              {block.level === 2 && <Rule className="mb-4" />}
            </div>
          );
        }

        if (block.kind === "paragraph") {
          return (
            <p
              key={index}
              className="mb-4"
              style={{
                fontSize: "var(--text-body)",
                lineHeight: 1.6,
                color: "var(--text-secondary)",
              }}
            >
              <Inlines nodes={block.text} />
            </p>
          );
        }

        if (block.kind === "list") {
          const Tag = block.ordered ? "ol" : "ul";
          return (
            <Tag
              key={index}
              className="mb-4 pl-5"
              style={{
                listStyleType: block.ordered ? "decimal" : "disc",
                fontSize: "var(--text-body)",
                lineHeight: 1.6,
                color: "var(--text-secondary)",
              }}
            >
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex} className="mb-1.5">
                  <Inlines nodes={item.text} />
                  {item.children.length > 0 && (
                    <ul className="mt-1.5 mb-1 pl-5" style={{ listStyleType: "circle" }}>
                      {item.children.map((child, childIndex) => (
                        <li key={childIndex} className="mb-1">
                          <Inlines nodes={child} />
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </Tag>
          );
        }

        return (
          <Panel key={index} className="mb-6 overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  {block.head.map((cell, cellIndex) => (
                    <th
                      key={cellIndex}
                      scope="col"
                      className="px-3 py-2 text-left font-mono uppercase"
                      style={{
                        fontSize: "var(--text-micro)",
                        letterSpacing: "0.12em",
                        color: "var(--text-tertiary)",
                        borderBottom: "1px solid var(--line-strong)",
                        fontWeight: 400,
                      }}
                    >
                      <Inlines nodes={cell} />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {block.rows.map((row, rowIndex) => (
                  <tr key={rowIndex} style={{ borderBottom: "1px solid var(--line-hairline)" }}>
                    {row.map((cell, cellIndex) => (
                      <td
                        key={cellIndex}
                        className="px-3 py-2 align-top"
                        style={{
                          fontSize: "var(--text-small)",
                          color: "var(--text-primary)",
                          lineHeight: 1.5,
                        }}
                      >
                        <Inlines nodes={cell} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        );
      })}
    </article>
  );
}
