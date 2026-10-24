import { useState } from "react";
import type { QuizItem } from "../lib/types";

export function Quiz({ items }: { items: QuizItem[] }) {
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const score = items.filter((q, i) => answers[i] === q.answer_index).length;
  return (
    <div className="quiz">
      <p className="meta" aria-live="polite">{Object.keys(answers).length ? `${score} / ${items.length} correct` : `${items.length} questions on today's news`}</p>
      <ol>
        {items.map((q, i) => {
          const chosen = answers[i];
          return (
            <li key={i}>
              <p className="quiz-q">{q.question}</p>
              <div className="options">
                {q.options.map((opt, j) => {
                  const state = chosen === undefined ? "" : j === q.answer_index ? "correct" : j === chosen ? "wrong" : "";
                  return (
                    <button key={j} type="button" className={`option ${state}`} disabled={chosen !== undefined}
                      onClick={() => setAnswers({ ...answers, [i]: j })}>{opt}</button>
                  );
                })}
              </div>
              {chosen !== undefined && <p className="explanation">{q.explanation}</p>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
