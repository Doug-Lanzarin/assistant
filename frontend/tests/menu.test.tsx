import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it } from "vitest";
import App from "../src/App";
import { mockBackend, STATUS } from "./helpers";

async function loggedIn() {
  localStorage.setItem("jarvis.token", "tok");
  location.hash = "#/jarvis";
  mockBackend({ "GET /api/auth/me": { username: "doug" }, "GET /api/settings": { voice: {} }, "GET /api/status": STATUS });
  const view = render(<App />);
  await screen.findByText("Sessão de voz encerrada");
  return view;
}

describe("menu lateral", () => {
  it("começa fechado e abre só ao clicar", async () => {
    const { container } = await loggedIn();
    const toggle = screen.getByRole("button", { name: "Abrir menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("navigation", { name: "Navegação principal" })).toBeNull();
    await userEvent.click(toggle);
    expect(screen.getByRole("navigation", { name: "Navegação principal" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Fechar menu" })).toHaveAttribute("aria-expanded", "true");
    expect(document.activeElement).toHaveTextContent("JARVIS"); // foco no primeiro item
    const res = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
  });

  it("fecha ao navegar, ao clicar fora e com Esc", async () => {
    await loggedIn();
    await userEvent.click(screen.getByRole("button", { name: "Abrir menu" }));
    await userEvent.click(screen.getByRole("button", { name: /Painel/ }));
    await waitFor(() => expect(location.hash).toBe("#/dashboard"));
    expect(screen.queryByRole("navigation", { name: "Navegação principal" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Abrir menu" }));
    await userEvent.click(document.querySelector(".menu-scrim") as HTMLElement);
    expect(screen.queryByRole("navigation", { name: "Navegação principal" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Abrir menu" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("navigation", { name: "Navegação principal" })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Abrir menu" }));
  });
});
