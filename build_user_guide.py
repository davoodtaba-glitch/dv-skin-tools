from fpdf import FPDF

FONT = r"C:\Windows\Fonts\arial.ttf"
FONT_B = r"C:\Windows\Fonts\arialbd.ttf"
FONT_I = r"C:\Windows\Fonts\ariali.ttf"
OUT = r"G:\grok\dv_skin tools\DV_Skin_Tools_User_Guide.pdf"

INK = (28, 30, 34)
MUTED = (90, 94, 102)
ACCENT = (28, 110, 164)
RULE = (210, 214, 220)
BAND = (245, 247, 250)
WHITE = (255, 255, 255)


class Guide(FPDF):
    def header(self):
        if self.page_no() == 1:
            return
        self.set_fill_color(*WHITE)
        self.rect(0, 0, self.w, 16, "F")
        self.set_xy(self.l_margin, 7)
        self.set_font("Body", "B", 8)
        self.set_text_color(*ACCENT)
        self.cell(90, 5, "DV SKIN TOOLS")
        self.set_font("Body", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 5, "User Guide  ·  0.8.24", align="R")
        self.set_draw_color(*RULE)
        self.set_line_width(0.3)
        self.line(self.l_margin, 14.5, self.w - self.r_margin, 14.5)
        self.set_y(20)

    def footer(self):
        if self.page_no() == 1:
            return
        self.set_y(-14)
        self.set_draw_color(*RULE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_y(-12)
        self.set_font("Body", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 6, str(self.page_no()), align="C")


def left(pdf):
    pdf.set_x(pdf.l_margin)


def h1(pdf, num, title):
    pdf.ln(7)
    left(pdf)
    pdf.set_fill_color(*ACCENT)
    pdf.rect(pdf.l_margin, pdf.get_y(), 2.2, 8, "F")
    pdf.set_xy(pdf.l_margin + 6, pdf.get_y())
    pdf.set_font("Body", "B", 14)
    pdf.set_text_color(*INK)
    pdf.cell(0, 8, f"{num}  {title}")
    pdf.ln(11)


def h2(pdf, title):
    pdf.ln(3)
    left(pdf)
    pdf.set_font("Body", "B", 11)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 6, title)
    pdf.ln(7)


def p(pdf, text):
    left(pdf)
    pdf.set_font("Body", "", 10)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 5.4, text)
    pdf.ln(2)


def item(pdf, name, text):
    left(pdf)
    pdf.set_font("Body", "B", 10)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 5.2, name)
    left(pdf)
    pdf.set_font("Body", "", 10)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 5.2, text)
    pdf.ln(2.4)


def bullets(pdf, lines):
    usable = pdf.w - pdf.l_margin - pdf.r_margin
    for line in lines:
        left(pdf)
        y = pdf.get_y()
        if y > pdf.h - 22:
            pdf.add_page()
            y = pdf.get_y()
        pdf.set_fill_color(*ACCENT)
        pdf.circle(pdf.l_margin + 1.6, y + 2.4, 0.7, "F")
        pdf.set_xy(pdf.l_margin + 6, y)
        pdf.set_font("Body", "", 10)
        pdf.set_text_color(*INK)
        pdf.multi_cell(usable - 6, 5.2, line)
        pdf.ln(0.6)
    pdf.ln(1.5)


def kv_table(pdf, rows):
    usable = pdf.w - pdf.l_margin - pdf.r_margin
    c1 = usable * 0.32
    c2 = usable - c1

    def header_row():
        left(pdf)
        pdf.set_font("Body", "B", 8)
        pdf.set_fill_color(*ACCENT)
        pdf.set_text_color(*WHITE)
        pdf.cell(c1, 7, "  Control", fill=True)
        pdf.cell(c2, 7, "  What it does", fill=True)
        pdf.ln(7)

    header_row()
    fill = False
    for a, b in rows:
        pdf.set_font("Body", "B", 9)
        h_a = pdf.multi_cell(c1 - 4, 4.6, a, dry_run=True, output="HEIGHT")
        pdf.set_font("Body", "", 9)
        h_b = pdf.multi_cell(c2 - 4, 4.6, b, dry_run=True, output="HEIGHT")
        h = max(h_a, h_b) + 3.2
        if pdf.get_y() + h > pdf.h - 18:
            pdf.add_page()
            header_row()
        bg = BAND if fill else WHITE
        x = pdf.l_margin
        y = pdf.get_y()
        pdf.set_fill_color(*bg)
        pdf.rect(x, y, usable, h, "F")
        pdf.set_text_color(*INK)
        pdf.set_xy(x + 2, y + 1.5)
        pdf.set_font("Body", "B", 9)
        pdf.multi_cell(c1 - 4, 4.6, a)
        pdf.set_xy(x + c1 + 2, y + 1.5)
        pdf.set_font("Body", "", 9)
        pdf.multi_cell(c2 - 4, 4.6, b)
        pdf.set_y(y + h)
        fill = not fill
    pdf.ln(3)


def cover(pdf):
    pdf.set_fill_color(*ACCENT)
    pdf.rect(0, 0, 12, pdf.h, "F")
    pdf.set_fill_color(18, 78, 122)
    pdf.rect(0, 0, 12, 8, "F")
    pdf.set_xy(28, 72)
    pdf.set_font("Body", "B", 11)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 7, "BLENDER ADD-ON")
    pdf.ln(14)
    pdf.set_x(28)
    pdf.set_font("Body", "B", 32)
    pdf.set_text_color(*INK)
    pdf.cell(0, 14, "DV Skin Tools")
    pdf.ln(16)
    pdf.set_x(28)
    pdf.set_font("Body", "", 14)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(150, 7, "Maya-style multi-influence skinning\nfor Blender Weight Paint")
    pdf.ln(18)
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.8)
    pdf.line(28, pdf.get_y(), 88, pdf.get_y())
    pdf.ln(10)
    pdf.set_x(28)
    pdf.set_font("Body", "", 11)
    pdf.set_text_color(*INK)
    pdf.cell(0, 6, "User Guide")
    pdf.ln(7)
    pdf.set_x(28)
    pdf.set_font("Body", "", 10)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 6, "Version 0.8.24  ·  Blender 4.2 and later")
    pdf.set_y(pdf.h - 28)
    pdf.set_x(28)
    pdf.set_font("Body", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, "Hover any control in Blender for the same descriptions used here.")


def main():
    pdf = Guide(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 18, 18)
    pdf.add_font("Body", "", FONT)
    pdf.add_font("Body", "B", FONT_B)
    pdf.add_font("Body", "I", FONT_I)

    pdf.add_page()
    cover(pdf)

    pdf.add_page()
    h1(pdf, "01", "Introduction")
    p(
        pdf,
        "DV Skin Tools is a Weight Paint add-on for Blender. It paints every deform influence at once, "
        "the way Maya skinning tools do, instead of Blender's default heatmap which only shows the active bone.",
    )
    p(
        pdf,
        "Use it to smooth, sharpen, replace, add, or remove weights; bind vertices to the nearest bone; "
        "mirror and copy skin; and display all influences as a multi-color overlay.",
    )
    p(
        pdf,
        "Open the 3D Viewport, press N, and select the DV Skin Tools tab. Most of the add-on is available "
        "in Weight Paint mode. In Object Mode the tab offers a button to enter Weight Paint.",
    )

    h1(pdf, "02", "Install")
    bullets(
        pdf,
        [
            "Edit > Preferences > Get Extensions (or Add-ons) > Install from Disk.",
            "Choose dv_skin_tool-0.8.26.zip and enable DV Skin Tools.",
            "If an older Skin Tools or DV Skin Tools add-on is installed, remove it first.",
        ],
    )

    h1(pdf, "03", "Quick start")
    bullets(
        pdf,
        [
            "Select a mesh that has an Armature modifier.",
            "Enter Weight Paint. From Object Mode, use Go to Weight Paint in the tab.",
            "Click Paint. The N-panel stays usable while you paint.",
            "Pick an influence in the list, or hold S and release over a bone.",
            "Stop with Stop Brush, Esc, or right-click.",
        ],
    )
    p(
        pdf,
        "The mouse wheel still zooms the view. Brush size is F. Intensity is Shift+F. "
        "The active influence is the selected pose bone, which stays in sync with the active vertex group.",
    )

    h1(pdf, "04", "Shortcuts")
    kv_table(
        pdf,
        [
            ("LMB", "Paint under the brush."),
            ("F", "Resize radius. Press F, drag left or right, LMB to confirm. RMB or Esc cancels."),
            ("Shift+F", "Adjust intensity the same way as F."),
            ("Hold Shift", "Temporarily use the DV Skin brush. Release Shift to restore the previous brush. Ignored over the UI."),
            ("Hold S", "Inspect and pick an influence. S always adds."),
            ("Hold D", "With Live Select on, hover subtracts bones from the selection."),
            ("Esc / RMB", "Stop the brush and restore Blender's default brush."),
            ("Ctrl+Z", "Undo the last DV Skin stroke, flood, or bind. The overlay stays on."),
            ("Ctrl+Shift+Z", "Redo the last undone DV Skin edit."),
        ],
    )

    h1(pdf, "05", "The Paint button")
    p(
        pdf,
        "Paint starts a session that smooths all bone influences together. This is not Blender's Blur brush, "
        "which only edits the active group.",
    )
    p(
        pdf,
        "While the session runs, the panel shows the current mode and Stop Brush. Stop Brush exits DV Skin "
        "and restores Blender's default brush and overlay.",
    )

    h1(pdf, "06", "Brush modes")
    p(pdf, "Mode chooses the operation applied under the brush. Each mode remembers its last Intensity.")
    kv_table(
        pdf,
        [
            ("Smooth", "Average all influences with neighboring vertices."),
            ("Sharpen", "Push weights away from the neighbor average to restore definition."),
            ("Stitch", "Blend border vertices toward their partner across open seam gaps."),
            ("Replace", "Set the active bone to Intensity."),
            ("Add", "Add Intensity to the active bone."),
            ("Remove", "Subtract Intensity from the active bone."),
        ],
    )

    h1(pdf, "07", "Flood and Interactive Mirror Paint")
    item(
        pdf,
        "Flood",
        "Applies the current brush mode to the whole mesh, or only to the weight-paint mask if one is active.",
    )
    item(
        pdf,
        "Interactive Mirror Paint",
        "Also paints the mirrored vertex across local X, using the mirrored bone. For example, painting R.arm "
        "also paints L.arm on the other side. Pairs are mutual opposites and the midline is skipped so the chest "
        "does not pick the wrong vertex. Replace, Add, and Remove paint the mirrored bone; Smooth and Sharpen "
        "stay a symmetric multi-influence operation. Right-click the toggle to assign a shortcut or add it to Quick Favorites.",
    )

    h1(pdf, "08", "Brush settings")
    kv_table(
        pdf,
        [
            ("Intensity", "Brush strength. Smooth, Add, and Remove blend by this amount. Replace uses it as the target weight."),
            ("Iterations", "Repeat the smooth inside each stamp. Higher values spread faster on dense meshes."),
            ("Radius", "Brush radius in scene units."),
            ("Falloff", "How strength drops from the center to the edge: Smooth, Linear, Sphere, or Constant (full strength inside the radius)."),
            ("Neighbors", "Smooth and Sharpen only. Surface averages along mesh edges. Volume averages nearby vertices in space, including across gaps and thin surfaces."),
            ("Volume Radius", "Search radius for volume neighbors. 0 uses a multiple of average edge length."),
            ("Only Existing Influences", "Do not add new influences to a vertex. Leave this off to blend between bones."),
            ("Skip Border Edges", "Leave vertices on open boundary edges out of Smooth and Sharpen, so seams cannot pull apart."),
            ("Sync Border Weights", "While smoothing, keep split-seam borders matched. Partners within Stitch Threshold are averaged after every stamp. If there is no matching vertex, weights are interpolated on the nearest edge of the other border."),
            ("Stitch Threshold", "Max distance between border vertex pairs for Stitch and Sync Border Weights, in local mesh units. 0 derives it from half the average edge length."),
            ("Projection", "Surface picks vertices near the hit point. Screen picks vertices near the mouse in screen space, including both sides of the mesh."),
            ("Target", "All Deform changes every deform bone (locked groups stay preserved). Selected Bones changes only selected pose bones; others are treated as locked."),
        ],
    )

    h1(pdf, "09", "Bind, remove, and add influences")
    h2(pdf, "Bind Nearest")
    p(
        pdf,
        "Replaces all current skin weights. Each vertex gets 1.0 on the closest bone and 0 on every other bone. "
        "Distance is measured to the bone segment from head to tail, in world space. Colors re-roll after a bind.",
    )
    bullets(
        pdf,
        [
            "Selected (bone icon) on: only selected pose bones compete. Off: all deform bones compete.",
            "Mirror (mirror icon) on: the result is mirrored across X using the Mirror Skin Weights direction and threshold.",
            "A vertex or face mask limits the bind to those vertices. With no mask, the whole mesh is bound.",
        ],
    )
    h2(pdf, "Remove Selected")
    p(
        pdf,
        "Removes selected pose bones from the skin. Their weights are stripped from the vertices and are not "
        "redistributed, so a vertex total may drop below 1. Their vertex groups are deleted. Other bones keep "
        "their weights. Respects the paint mask. Undo with Ctrl+Z.",
    )
    h2(pdf, "Add Selected")
    p(
        pdf,
        "Creates vertex groups on the mesh for the selected pose bones. Bones that already have a group are skipped. "
        "The button stays available when a deform bone is chosen in All Bones. If the mesh has no Armature modifier, "
        "one is added and linked to that bone's armature.",
    )

    h1(pdf, "10", "Influence list")
    p(
        pdf,
        "The list shows deform vertex groups on the active mesh. Click a row to make that group the active paint "
        "influence. The matching pose bone is selected in the viewport. Locked groups show a lock icon.",
    )
    kv_table(
        pdf,
        [
            ("Live Select", "While holding S, hovering a bone adds it to the selection. Holding D and hovering subtracts it."),
            ("Invert", "Flips selection on every deform bone of the mesh's armature."),
            ("Deselect All", "Deselects all pose bones of the active mesh's armature."),
            ("Size", "How many rows the influence list shows."),
            ("Search", "Use the magnifying glass at the bottom of the list to filter by name. Invert and A-Z sort sit on the same bar."),
        ],
    )

    h1(pdf, "11", "All Bones")
    p(
        pdf,
        "This rollout lists every deform bone in the scene — bones whose Deform option is on in Bone Properties. "
        "Non-deform bones are hidden. Clicking a name does not select the bone; use the checkbox. "
        "The list has its own name filter at the bottom.",
    )
    p(
        pdf,
        "Use it to find bones that are not influences yet, check them, then click Add Selected to create vertex groups.",
    )

    h1(pdf, "12", "Display")
    kv_table(
        pdf,
        [
            ("Bone X-Ray", "Draw the skin's armature on top of the influence colors, like the armature's In Front display."),
            ("X-Ray All Bones", "Draw every bound bone through the mesh, even if its collection is invisible, the bone is hidden, or the armature object is hidden."),
            ("Show All Influences", "Color the mesh by every bone at once, like Maya. Replaces the blue-red heatmap. On by default in Weight Paint."),
            ("Overlay Opacity", "Opacity of the multi-color influence display."),
            ("Wireframe", "Draw the mesh wireframe over the Show All Influences colors."),
            ("Randomize Colors", "New colors for the overlay only. Weights do not change."),
        ],
    )
    p(
        pdf,
        "Object Mode turns Show All Influences off so the mesh is not left hidden. It comes back when you enter Weight Paint. "
        "Right-click X-Ray All Bones or Show All Influences to assign a shortcut.",
    )

    h1(pdf, "13", "Pick Influence")
    p(
        pdf,
        "Hold S to inspect influences. Bound bones show in x-ray. The active influence is green with white vertices. "
        "The bone under the mouse previews in red.",
    )
    bullets(
        pdf,
        [
            "Live Select off: release S to pick the hovered bone. LMB also confirms. Esc or RMB cancels.",
            "Live Select on: holding S adds hovered bones to the selection. Holding D subtracts them. Releasing the key ends the pass.",
            "S is always add. D is always subtract. The physical key that started the session decides the mode.",
            "Clicks on menus, the N-panel, and headers belong to the UI, not the picker.",
        ],
    )

    h1(pdf, "14", "Advanced")
    p(pdf, "This sub-panel is shown in Weight Paint, or while a paint session is running.")
    kv_table(
        pdf,
        [
            ("Front Faces Only", "Ignore vertices facing away from the view."),
            ("Airbrush", "Keep applying while the mouse is held still."),
            ("Tablet Pressure", "Multiply intensity by stylus pressure."),
            ("Spacing", "Minimum travel, as a fraction of radius, before the next stamp."),
            ("Max Influences", "Cap influences per vertex after smoothing. 0 means no extra cap."),
            ("Prune", "Weights at or below this are removed after smoothing."),
            ("Mirror Pattern", "Optional example bone for your side names, such as R-arm, Arm_R, or RIGHT_arm. Interactive Mirror Paint and Mirror Weights try this rule first, then built-in .L / .R. Leave empty to use built-ins only."),
        ],
    )
    p(
        pdf,
        "If the pattern is recognized, the panel shows the detected rule. If not, built-in .L / .R names are used.",
    )

    h1(pdf, "15", "Mirror Skin Weights")
    p(
        pdf,
        "Copies skin weights across the local X axis and flips .L / .R bone names (or your Mirror Pattern). "
        "Vertices are paired on the rest mesh, so it works even when the armature is posed.",
    )
    kv_table(
        pdf,
        [
            ("+X to -X", "Copy from the +X side onto the -X side (left to right)."),
            ("-X to +X", "Copy from the -X side onto the +X side (right to left)."),
            ("Heavier Side", "For mutual pairs, the side with more total weight wins."),
            ("Mirror Threshold", "Max distance between mirror vertex pairs, in local mesh units. 0 derives it from average edge length."),
        ],
    )

    h1(pdf, "16", "Transfer Skin Weights")
    h2(pdf, "Copy between meshes")
    p(
        pdf,
        "Copies skin from source mesh(es) onto the active mesh. Missing vertex groups are created. "
        "The vertex paint mask and locked groups are respected.",
    )
    kv_table(
        pdf,
        [
            ("Use Selected as Sources", "The active mesh is the target. Every other selected mesh is a source. Each target vertex takes weights from the nearest source surface, so one mesh can follow several overlapping garments."),
            ("Source Object", "Used when Use Selected as Sources is off. The skinned mesh to copy from."),
            ("Closest point on surface", "Interpolate source weights at the closest point on the source surface."),
            ("Nearest vertex", "Take the weights of the nearest source vertex."),
            ("Closest joint", "Match influences by name first, then by nearest bone joint position."),
            ("Name lookup", "Only match influences with identical names."),
            ("One-to-one", "Match vertex groups by their order in the list."),
            ("Normalize", "Scale copied weights so they sum to 1.0 per vertex."),
            ("Remove Empty Groups", "Delete vertex groups that have no weights on this mesh. Works in Object Mode and Weight Paint."),
        ],
    )
    h2(pdf, "Export and import")
    p(
        pdf,
        "Export writes every vertex group's per-vertex weights to JSON, stored by group name and vertex index. "
        "Use it as a backup or to transfer onto a mesh with matching vertex order.",
    )
    p(
        pdf,
        "Import reads that JSON onto the active mesh. Groups are matched by name; missing ones are created. "
        "Locked groups are protected. Works in Object Mode and Weight Paint.",
    )

    h1(pdf, "17", "Undo")
    p(
        pdf,
        "Ctrl+Z undoes the last DV Skin stroke, flood, or bind. Ctrl+Shift+Z redoes it. "
        "Show All Influences stays on and colors follow the restored weights. "
        "Removing selected bones: weight undo restores stripped weights; Blender undo restores the deleted groups.",
    )

    h1(pdf, "18", "Workflow notes")
    bullets(
        pdf,
        [
            "Leave Only Existing Influences off when you want the brush to blend between bones.",
            "Lock a vertex group in Blender to protect it. Locked groups are always preserved.",
            "Target = Selected Bones, plus checkboxes in the influence list, is the usual multi-bone setup.",
            "Set Mirror Pattern once if the rig does not use .L / .R names.",
            "Flood and Bind Nearest both honor the weight-paint vertex or face mask.",
            "Interactive Mirror Paint and Mirror Skin Weights both use Mirror Pattern, then built-in L/R rules.",
        ],
    )

    pdf.output(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
