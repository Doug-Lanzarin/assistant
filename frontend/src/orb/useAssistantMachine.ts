import { useCallback, useRef, useState } from "react";
import { initialMachine, transition, type AssistantEvent, type AssistantState, type MachineState } from "./stateMachine";

export interface TransitionLog {
  at: number;
  event: AssistantEvent["type"];
  from: AssistantState;
  to: AssistantState;
}

declare global {
  interface Window {
    __jarvisMachine?: () => { current: MachineState; log: TransitionLog[] };
  }
}

/** Mantém a máquina de estados e um histórico das transições (para diagnóstico e testes E2E). */
export function useAssistantMachine() {
  const [machine, setMachine] = useState<MachineState>(() => initialMachine(performance.now()));
  const ref = useRef(machine);
  const log = useRef<TransitionLog[]>([]);

  const dispatch = useCallback((e: AssistantEvent) => {
    const prev = ref.current;
    const next = transition(prev, e, performance.now());
    if (next === prev) return prev;
    if (next.state !== prev.state) {
      log.current.push({ at: Math.round(next.since), event: e.type, from: prev.state, to: next.state });
      if (log.current.length > 200) log.current.shift();
    }
    ref.current = next;
    setMachine(next);
    return next;
  }, []);

  if (typeof window !== "undefined") window.__jarvisMachine = () => ({ current: ref.current, log: [...log.current] });

  return { machine, dispatch, current: ref };
}
