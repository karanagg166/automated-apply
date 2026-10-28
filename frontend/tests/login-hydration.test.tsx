import { renderToString } from "react-dom/server";
import { expect, it } from "vitest";
import Login from "@/app/login/page";

it("server-rendered login cannot send a passphrase through a GET before hydration", () => {
  const document = new DOMParser().parseFromString(
    renderToString(<Login />),
    "text/html",
  );
  const form = document.querySelector("form")!;
  expect(form.getAttribute("method")).toBe("post");
  expect(form.getAttribute("action")).toBe("/api/auth");
  expect(
    form.querySelector<HTMLInputElement>('input[name="password"]')!.disabled,
  ).toBe(true);
  expect(
    form.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled,
  ).toBe(true);
});
