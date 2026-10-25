import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { UNKNOWN_TAG } from "../src/data/fixtures";
import { convexMock } from "./convexMock";
import { renderAt, serve } from "./harness";

vi.mock("../src/lib/photo", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/lib/photo")>()),
  downscalePhoto: vi.fn(async () => new Blob([new Uint8Array(2048)], { type: "image/jpeg" })),
}));

const user = () => userEvent.setup();

function itemEntry(name: string) {
  return screen.getByRole("heading", { level: 3, name }).closest("li")!;
}

describe("Items", () => {
  it("lists every item with its other names, home spot, and notes", () => {
    serve();
    renderAt("/items");
    expect(screen.getByRole("heading", { level: 1, name: "Items" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Your items (5)" })).toBeInTheDocument();
    const salt = itemEntry("Salt");
    expect(salt).toHaveTextContent("table salt, sea salt");
    expect(salt).toHaveTextContent("Center left");
    expect(salt).toHaveTextContent("For cooking and for eggs.");
    expect(itemEntry("Keys")).toHaveTextContent("fob_keys");
    expect(itemEntry("Blood pressure pills")).toHaveTextContent("Medication");
  });

  it("edits an item and sends only the changed fields", async () => {
    serve();
    renderAt("/items");
    const u = user();
    await u.click(screen.getByRole("button", { name: "Edit Salt" }));
    const form = screen.getByRole("form", { name: "Edit Salt" });
    const name = within(form).getByLabelText("Name");
    await u.clear(name);
    await u.type(name, "sea salt");
    await u.selectOptions(within(form).getByLabelText("Home spot"), "Spot 1: far left");
    await u.click(within(form).getByRole("button", { name: "Save changes" }));
    expect(convexMock.mutation("objects:update")).toHaveBeenCalledWith({ objectId: "salt", name: "sea salt", homeSpot: 1 });
    expect(await screen.findByText(/Saved changes to sea salt/)).toBeInTheDocument();
  });

  it("requires a name and says so next to the field", async () => {
    serve();
    renderAt("/items");
    const u = user();
    await u.click(screen.getByRole("button", { name: "Add by hand" }));
    await u.click(screen.getByRole("button", { name: "Save item" }));
    const name = screen.getByLabelText("Name");
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveAccessibleDescription(expect.stringContaining('Enter a name, for example "sugar".'));
    expect(name).toHaveFocus();
    expect(convexMock.mutation("objects:create")).not.toHaveBeenCalled();
  });

  it("labels an unknown tag from the map's link, prefilled with its tag and spot", async () => {
    serve();
    renderAt(`/items?label=${UNKNOWN_TAG}`);
    const u = user();
    expect(screen.getByRole("heading", { name: "Add an item for the new item on the far left spot" })).toBeInTheDocument();
    expect(screen.getByLabelText("Spot tag ID")).toHaveValue(UNKNOWN_TAG);
    expect(screen.getByLabelText("Home spot")).toHaveValue("1");
    await u.type(screen.getByLabelText("Name"), "honey");
    await u.type(screen.getByLabelText("Other names"), "honey jar, , Honey jar, squeeze honey");
    await u.click(screen.getByRole("button", { name: "Save item" }));
    expect(convexMock.mutation("objects:create")).toHaveBeenCalledWith({
      name: "honey",
      aliases: ["honey jar", "squeeze honey"],
      notes: "",
      description: "",
      tag: UNKNOWN_TAG,
      homeSpot: 1,
      isMedication: false,
      fobId: null,
    });
  });

  it("deletes only after an in-page confirmation, never a browser dialog", async () => {
    serve();
    renderAt("/items");
    const confirmSpy = vi.spyOn(window, "confirm");
    const u = user();
    await u.click(screen.getByRole("button", { name: "Edit Pepper" }));
    await u.click(screen.getByRole("button", { name: "Delete Pepper" }));
    const group = screen.getByRole("group", { name: "Delete Pepper?" });
    expect(group).toHaveFocus();
    expect(convexMock.mutation("objects:remove")).not.toHaveBeenCalled();
    await u.click(within(group).getByRole("button", { name: "Keep Pepper" }));
    expect(screen.queryByRole("group", { name: "Delete Pepper?" })).not.toBeInTheDocument();
    expect(convexMock.mutation("objects:remove")).not.toHaveBeenCalled();

    await u.click(screen.getByRole("button", { name: "Edit Pepper" }));
    await u.click(screen.getByRole("button", { name: "Delete Pepper" }));
    await u.click(screen.getByRole("button", { name: "Yes, delete Pepper" }));
    expect(convexMock.mutation("objects:remove")).toHaveBeenCalledWith({ objectId: "pepper" });
    expect(confirmSpy).not.toHaveBeenCalled();
  });
});

describe("Photo-assisted labeling", () => {
  function photoSetup() {
    convexMock.mutation("labeling:generateUploadUrl").mockResolvedValue("https://upload.example/abc");
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ storageId: "storage-1" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }
  const photo = () => new File([new Uint8Array(4096)], "honey.heic", { type: "image/heic" });

  it("uploads, suggests, lets the person edit, and saves only on confirmation", async () => {
    serve();
    const fetchMock = photoSetup();
    convexMock.action("labeling:suggestFromPhoto").mockResolvedValue({
      name: "honey",
      aliases: ["honey jar", "squeeze honey"],
      description: "Plastic squeeze bottle shaped like a bear.",
      model: "test-vision-model",
      latencyMs: 2300,
      photoDeleted: true,
    });
    renderAt("/items");
    const u = user();
    await u.click(screen.getByRole("button", { name: "Start from a photo" }));
    expect(screen.getByText(/no cameras in the home\. This one photo comes from your own phone or computer\./)).toBeInTheDocument();
    const take = screen.getByLabelText("Take a photo");
    expect(take).toHaveAttribute("accept", "image/*");
    expect(take).toHaveAttribute("capture", "environment");
    await u.upload(screen.getByLabelText("Choose a photo"), photo());

    expect(await screen.findByRole("heading", { name: "Check the suggestion" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "https://upload.example/abc",
      expect.objectContaining({ method: "POST", headers: { "Content-Type": "image/jpeg" } }),
    );
    expect(convexMock.action("labeling:suggestFromPhoto")).toHaveBeenCalledWith({ storageId: "storage-1" });
    expect(screen.getByText("Photo deleted.")).toBeInTheDocument();
    expect(screen.getByText(/Suggested by test-vision-model in 2\.3 s/)).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("honey");
    expect(screen.getByLabelText("Other names")).toHaveValue("honey jar, squeeze honey");
    expect(convexMock.mutation("objects:create")).not.toHaveBeenCalled();

    await u.clear(screen.getByLabelText("Name"));
    await u.type(screen.getByLabelText("Name"), "bear honey");
    await u.click(screen.getByRole("button", { name: "Save as a new item" }));
    expect(convexMock.mutation("objects:create")).toHaveBeenCalledWith({
      name: "bear honey",
      aliases: ["honey jar", "squeeze honey"],
      notes: "",
      description: "Plastic squeeze bottle shaped like a bear.",
      tag: null,
      homeSpot: null,
      isMedication: false,
      fobId: null,
    });
    expect(await screen.findByText(/Saved bear honey/)).toBeInTheDocument();
  });

  it("can update an existing item instead, sending only what changed", async () => {
    serve();
    photoSetup();
    convexMock.action("labeling:suggestFromPhoto").mockResolvedValue({
      name: "pepper",
      aliases: ["pepper mill"],
      description: "Tall wooden pepper grinder with a brass top.",
      model: "m",
      latencyMs: 900,
      photoDeleted: true,
    });
    renderAt("/items");
    const u = user();
    await u.click(screen.getByRole("button", { name: "Start from a photo" }));
    await u.selectOptions(screen.getByLabelText("Use the suggestion for"), "Pepper (update)");
    await u.upload(screen.getByLabelText("Choose a photo"), photo());
    await u.click(await screen.findByRole("button", { name: "Update Pepper" }));
    expect(convexMock.mutation("objects:update")).toHaveBeenCalledWith({
      objectId: "pepper",
      aliases: ["pepper mill"],
      description: "Tall wooden pepper grinder with a brass top.",
    });
  });

  it("explains a missing Anthropic key and saves nothing", async () => {
    serve();
    photoSetup();
    convexMock
      .action("labeling:suggestFromPhoto")
      .mockRejectedValue(
        new Error("[CONVEX A(labeling:suggestFromPhoto)] [Request ID: 1] Server Error\nUncaught Error: ANTHROPIC_API_KEY is not set\n    at handler"),
      );
    renderAt("/items");
    const u = user();
    await u.click(screen.getByRole("button", { name: "Start from a photo" }));
    await u.upload(screen.getByLabelText("Choose a photo"), photo());
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Photo suggestions are not set up on this Earmark server yet (no Anthropic API key)");
    expect(alert).toHaveTextContent("Nothing was saved.");
    expect(screen.queryByText("Photo deleted.")).not.toBeInTheDocument();
    expect(convexMock.mutation("objects:create")).not.toHaveBeenCalled();

    await u.click(screen.getByRole("button", { name: "Fill in by hand instead" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "New item" })).toBeInTheDocument());
  });

  it("reports a failed upload without calling the model", async () => {
    serve();
    convexMock.mutation("labeling:generateUploadUrl").mockResolvedValue("https://upload.example/abc");
    vi.stubGlobal("fetch", vi.fn(async () => new Response("nope", { status: 500 })));
    renderAt("/items");
    const u = user();
    await u.click(screen.getByRole("button", { name: "Start from a photo" }));
    await u.upload(screen.getByLabelText("Choose a photo"), photo());
    expect(await screen.findByRole("alert")).toHaveTextContent("The photo upload failed (HTTP 500).");
    expect(convexMock.action("labeling:suggestFromPhoto")).not.toHaveBeenCalled();
  });
});
