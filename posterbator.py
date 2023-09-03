#!/usr/bin/env python3
# coding=utf-8
#
# Copyright (C) 2023 Roman Penyaev
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
"""
Posterbator - creates posters!
"""

import os
import math
import random
from shutil import copy2
import inkex

from inkex.transforms import (
    BoundingBox,
    Vector2d,
)

from inkex import (
    Page,
    Group,
    PathElement,
    Rectangle,
    Transform,
    TextElement,
    Style
)

COLOR_PALETTE = (
    "#0000ff",
    "#ff0000",
    "#00e000",
    "#d0d000",
    "#ff8000",
    "#00e0e0",
    "#ff00ff",
    "#b4b4b4",
    "#0000a0",
    "#a00000",
    "#00a000",
    "#a0a000",
    "#c08000",
    "#00a0ff",
    "#a000a0",
    "#808080",
    "#7d87b9",
    "#bb7784",
    "#4a6fe3",
    "#d33f6a",
)

def rm_file(tempfile):
    try:
        os.remove(tempfile)
    except Exception:  # pylint: disable=broad-except
        pass

def get_inkscape_version():
    try: # needed prior to 1.1
        ink_version = inkex.command.inkscape('--version').decode("utf-8")
    except AttributeError: # needed starting from 1.1
        ink_version = inkex.command.inkscape('--version')

    pos = ink_version.find("Inkscape ")
    if pos != -1:
        pos += 9
    else:
        return None
    v_num = ink_version[pos:pos+3]
    return(v_num)

def get_defs(node):
    """Find <defs> in children of *node*, return first one found."""
    path = '/svg:svg//svg:defs'
    try:
        return node.xpath(path, namespaces=inkex.NSS)[0]
    except IndexError:
        return etree.SubElement(node, inkex.addNS('defs', 'svg'))

def get_page_number_str(page_idx):
    return "%s%d" % (chr(65 + page_idx[0]), page_idx[1] + 1)

def inkscape_stdout_to_ids(stdout):
    ids = []
    for line in stdout.splitlines():
        ids.append(line.split(" ")[0])
    return ids

class Posterbator(inkex.EffectExtension):
    """Create a poster."""

    def add_arguments(self, pars):
        pars.add_argument("--tab")
        pars.add_argument(
            "--sheet-size",
            default="A4",
            dest="sheet_size",
            choices=["A4"],
            help="Defines sheet size",
        )
        pars.add_argument(
            "--sheet-orientation",
            default="landscape",
            dest="sheet_orientation",
            choices=["landscape", "portrait"],
            help="Defines sheet orientation",
        )
        pars.add_argument(
            "--margin",
            type=float,
            default=10.0,
            dest="margin",
            help="Margin in mm",
        )
        pars.add_argument(
            "--output-sheets-number",
            type=float,
            default=4.0,
            dest="output_sheets_number",
            help="Defines output sheets number",
        )
        pars.add_argument(
            "--output-sheet-orientation",
            default="wide",
            dest="output_sheet_orientation",
            choices=["wide", "high"],
            help="Defines output sheet orientation",
        )
        pars.add_argument(
            "--output-page-numbers",
            default="wide",
            dest="output_page_numbers",
            help="Defines output page numbers",
        )
        pars.add_argument(
            "--output-page-frames",
            default="wide",
            dest="output_page_frames",
            help="Defines output helper page frames",
        )
        pars.add_argument(
            "--output-holes-group",
            default="wide",
            dest="output_holes_group",
            help="Defines separate holes group",
        )
        pars.add_argument(
            "--output-use-palette",
            default="wide",
            dest="output_use_palette",
            help="Defines use palette",
        )

    # ----- workaround to avoid crash on quit

    # If selection set tagrefs have been deleted as a result of the
    # extension's modifications of the drawing content, inkscape will
    # crash when closing the document window later on unless the tagrefs
    # are checked and cleaned up manually by the extension script.

    # NOTE: crash on reload in the main process (after the extension has
    # finished) still happens if Selection Sets dialog was actually
    # opened and used in the current session ... the extension could
    # create fake (invisible) objects which reuse the ids?
    # No, fake placeholder elements do not prevent the crash on reload
    # if the dialog was opened before.

    # TODO: these checks (and the purging of obsolete tagrefs) probably
    # should be applied in Effect() itself, instead of relying on
    # workarounds in derived classes that modify drawing content.

    def has_tagrefs(self):
        """Check whether document has selection sets with tagrefs."""
        defs = get_defs(self.document.getroot())
        inkscape_tagrefs = defs.findall(
            "inkscape:tag/inkscape:tagref", namespaces=inkex.NSS)
        return len(inkscape_tagrefs) > 0

    def update_tagrefs(self, mode='purge'):
        """Check tagrefs for deleted objects."""
        defs = get_defs(self.document.getroot())
        inkscape_tagrefs = defs.findall(
            "inkscape:tag/inkscape:tagref", namespaces=inkex.NSS)
        if len(inkscape_tagrefs) > 0:
            for tagref in inkscape_tagrefs:
                href = tagref.get(inkex.addNS('href', 'xlink'))[1:]
                if self.svg.getElementById(href) is None:
                    if mode == 'purge':
                        tagref.getparent().remove(tagref)
                    elif mode == 'placeholder':
                        temp = etree.Element(inkex.addNS('path', 'svg'))
                        temp.set('id', href)
                        temp.set('d', 'M 0,0 Z')
                        self.document.getroot().append(temp)

    def __run_pathops(self, svgfile, cmds, dry_run):
        """Run path ops with top_path on a list of other object ids."""
        # build list with command line arguments
        # Version-dependent. This one is for Inkscape 1.1 (else it crashes, see https://gitlab.com/inkscape/inbox/-/issues/4905)
        ACTIONS = {
            "1.2": 
            {
                "dup": "duplicate",
                "un": "path-union",
                "diff": "path-difference",
                "inter": "path-intersection",
                "exclor": "path-exclusion",
                "div": "path-division",
                "cut": "path-cut",
                "comb": "path-combine",
                "split": "path-split",
                "break": "path-break-apart",
                "desel": "select-clear",
                "selection-ungroup-pop": "selection-ungroup-pop",
                "selection-group": "selection-group",
                "select-list": "select-list",
                "save": f"export-filename:{svgfile};export-overwrite;export-do",
            },
            "1.1":
            {
                "dup": "EditDuplicate",
                "un": "SelectionUnion",
                "diff": "SelectionDiff",
                "inter": "SelectionIntersect",
                "exclor": "SelectionSymDiff",
                "div": "SelectionDivide",
                "cut": "SelectionCutPath",
                "comb": "SelectionCombine",
                "desel": "EditDeselect",
                "save": "FileSave",
            },
            "1.0":
            {
                "dup": "EditDuplicate",
                "un": "SelectionUnion",
                "diff": "SelectionDiff",
                "inter": "SelectionIntersect",
                "exclor": "SelectionSymDiff",
                "div": "SelectionDivide",
                "cut": "SelectionCutPath",
                "comb": "SelectionCombine",
                "desel": "EditDeselect",
                "save": "FileSave",
            },
        }
        # Alias
        ACTIONS["1.3"] = ACTIONS["1.2"]

        inkversion = get_inkscape_version()
        actions_list = []
        duplicate_command = ACTIONS[inkversion]['dup']
        deselect_command = ACTIONS[inkversion]['desel']
        save_command = ACTIONS[inkversion]['save']

        for cmd in cmds:
            multi_cmds = []
            if type(cmd) is tuple:
                multi_cmds.append(cmd)
            elif type(cmd) is list:
                multi_cmds = cmd
            else:
                assert False, "Unknown cmd type, should tuple or list"
            for cmd in multi_cmds:
                objs, op, *_ = cmd
                for obj in objs:
                    actions_list.append("select-by-id:" + obj.get_id())
                if type(op) is tuple:
                    for op_str in op:
                        actions_list.append(ACTIONS[inkversion][op_str])
                else:
                    actions_list.append(ACTIONS[inkversion][op])
            actions_list.append(deselect_command)
        actions_list.append(save_command)

        if inkversion == "1.0":
            actions_list.append("FileQuit")
            extra_param = "--with-gui"
        elif inkversion == "1.1":
            extra_param = "--batch-process"
        else:
            extra_param = ""
        actions = ";".join(actions_list)
        stdout = ""
        # process command list
        if dry_run:
            inkex.utils.debug(" ".join(["inkscape", extra_param,
                                        "--actions=" + "\"" + actions + "\"",
                                        svgfile, f"(using Inkscape {inkversion})"]))
        else:
            if extra_param != "":
                stdout = inkex.command.inkscape(svgfile, extra_param, actions=actions)
            else:
                stdout = inkex.command.inkscape(svgfile, actions=actions)

        return stdout

    def run_pathops(self, cmds, dry_run=False):
        # Save current state to a temp file before proceeding with
        # path operations in order run_pathops() gets all the changes
        tempfile = self.options.input_file + "-pathops.svg"
        temp = open(tempfile, "wb")
        self.save(temp)
        temp.close()

        # Do path ops
        stdout = self.__run_pathops(tempfile, cmds, dry_run)

        # Replace current document with content of temp copy file
        self.document = inkex.load_svg(tempfile)
        rm_file(tempfile)
        # Update self.svg
        self.svg = self.document.getroot()
        self.update_tagrefs()

        return stdout

    def calculate_poster_size(self):
        # Obtain sheet size
        sheet_size = ()
        if self.options.sheet_size == "A4":
            sheet_size = (210, 297)
        else:
            assert False, "Incorrect sheet size!"

        # Obtain sheet orientation
        if self.options.sheet_orientation == "landscape":
            # Swap width and height
            sheet_size = (sheet_size[1], sheet_size[0])

        # Validate and obtain sheets number
        sheets_n = float(self.options.output_sheets_number)
        if sheets_n < 1 or sheets_n > 10:
            assert False, "Incorrect sheets number!"


        # Validate and obtain margin
        margin = float(self.options.margin)
        if margin < 0 or margin > 50:
            assert False, "Incorrect margin!"

        # Obtain selection bounding box
        sel_bbox = self.svg.selection.bounding_box()

        # Viewport of each sheet ratio
        image_per_sheet_ratio = (sheet_size[0] - 2 * margin) / (sheet_size[1] - 2 * margin)

        # Whole image selection ratio
        image_ratio = sel_bbox.width / sel_bbox.height

        # Calculate slice size and sheets number
        if self.options.output_sheet_orientation == "wide":
            slice_rect_width = sel_bbox.width / sheets_n
            slice_rect_height = slice_rect_width / image_per_sheet_ratio

            sheets_n_wide = math.ceil(sheets_n)
            sheets_n_high = math.ceil(1.0 / image_ratio * image_per_sheet_ratio * sheets_n)

            scale = ((sheet_size[0] - 2 * margin) * sheets_n) / sel_bbox.width
        else:
            slice_rect_height = sel_bbox.height / sheets_n
            slice_rect_width = slice_rect_height * image_per_sheet_ratio

            sheets_n_high = math.ceil(sheets_n)
            sheets_n_wide = math.ceil(image_ratio / image_per_sheet_ratio * sheets_n)

            scale = ((sheet_size[1] - 2 * margin) * sheets_n) / sel_bbox.height

        return (sheet_size,
                (slice_rect_width, slice_rect_height),
                (sheets_n_wide, sheets_n_high),
                margin, scale)

    def separate_holes(self, group_ids, holes_group_id):
        #
        # Here we prepare duplicates for making holes be "correct". What means
        # correct? If layers (selections) overlap and a bottom layer has hole,
        # this hole should not be visible, because it is covered by the top
        # layer. Here we make duplicates of all elements, combining them by
        # page. Once all holes are found (further operations along the code),
        # the difference between holes and this duplicated combined elements
        # should be found. Everything left after the difference operation -
        # is the "correct" hole!
        #

        # Map all elements by page numbers
        elems_map = {}
        for group_id in group_ids:
            group = self.svg.getElementById(group_id)
            if group is None:
                assert False, "Group can't be found! Assert!"
            for elem in group:
                page_number = elem.get_id().split("-")[0]
                elems = elems_map.setdefault(page_number, [])
                elems.append(elem)

        # Duplicate and combine all elements per page
        path_cmds = []
        page_numbers = []
        for page_number, elems in elems_map.items():
            page_numbers.append(page_number)
            path_cmds.append((elems, ("dup","comb","selection-ungroup-pop", "select-list")))

        # Duplicate and combine. The stdout list is duplicated elements
        # combined per page
        stdout = self.run_pathops(path_cmds)

        # Map duplicated elements per page for easy access further below
        dup_elem_ids = inkscape_stdout_to_ids(stdout)
        dup_elems_map = {}
        for i in range(0, len(dup_elem_ids)):
            elem = self.svg.getElementById(dup_elem_ids[i])
            if elem is None:
                assert False, "Elem can't be found! Assert!"
            page_number = page_numbers[i]
            id_str = "%s-%s" % (page_numbers[i], elem.get_id())
            elem.set_id(id_str)
            dup_elems_map[page_number] = id_str

        #
        # How to find holes?
        #
        # 1. "split" every element, which creates many separated elements
        # (paths) for compound objects, so each newly created element will
        # have only one shape (but shape with a hole will still contain a
        # hole).
        # 2. Store all elements after "split" operation into a list.
        # 3. "break apart" every element, which splits further and separates
        # holes from objects.
        # 4. Find the difference between stored list after "split" and current
        # list of elements, the difference list is the list with holes
        #

        #
        # Go over each element, place it in a separate nested group and then
        # call a "split", which creates new objects in a new nested group.
        #
        path_cmds = []
        nested_groups = []
        for group_id in group_ids:
            group = self.svg.getElementById(group_id)
            if group is None:
                assert False, "Group can't be found! Assert!"

            elems = []
            for elem in group:
                elems.append(elem)

            group.remove_all()

            # Put each element to a nested group, because new created
            # elements after "split" or "break-apart" path operations
            # are created in the group where the original element sits,
            # so finding new elements becomes easy.
            for elem in elems:
                nested = Group()
                group.append(nested)
                nested.set_id("%s-%s" % (elem.get_id().split("-")[0], nested.get_id()))
                nested.append(elem)
                nested_groups.append(nested)
                # Split all paths
                path_cmds.append(((elem,), "split"))

        # Do path split
        self.run_pathops(path_cmds)

        #
        # Go over each element after "split" and store it in the "known"
        # list, then "break apart", which possibly creates new hole
        # elements.
        #
        path_cmds = []
        known = {}
        for group_id in group_ids:
            group = self.svg.getElementById(group_id)
            if group is None:
                assert False, "Group can't be found! Assert!"

            for nested_group in group:
                for elem in nested_group:
                    known[elem.get_id()] = 1

                    # Break apart all paths
                    path_cmds.append(((elem,), "break"))

        # Do path break apart
        self.run_pathops(path_cmds)

        #
        # Find the difference between known list (after "split" operation)
        # and current list (after "break apart" operation). The difference
        # is our holes.
        #
        hole_map = {}
        for old_group in nested_groups:
            group = self.svg.getElementById(old_group.get_id())
            if group is None:
                assert False, "Group can't be found! Assert!"

            for elem in group:
                # If element is not known, that means it is a hole, which
                # appeared after breaking apart
                if elem.get_id() in known:
                    continue

                page_number = group.get_id().split("-")[0]
                holes = hole_map.setdefault(page_number, [])
                holes.append(elem)

        # Combine found holes by page.
        path_cmds = []
        for page_number, holes in hole_map.items():
            if len(holes) > 1:
                path_cmds.append((holes, "comb"))

        # Do combine holes in paths per group
        self.run_pathops(path_cmds)

        # Redefine holes group object because svg was changed
        holes_group = self.svg.getElementById(holes_group_id)
        if holes_group is None:
            assert False, "Holes group can't be found! Assert!"

        #
        # Rename holes, add them to a separate "holes" group and
        # make them white (background)
        #
        for page_number, holes in hole_map.items():
            # In UI it is the top, in the list it is the last.
            # After combine the resulting path gets the name of the
            # top element.
            top_hole = holes[-1]
            id_str = top_hole.get_id()
            elem = self.svg.getElementById(id_str)
            if elem is None:
                assert False, "Hole path can't be found! Assert!"
            # Rename hole
            elem.set_id("%s-%s" % (page_number, id_str))
            # Set white color (background)
            color = "white"
            if self.options.output_use_palette == "true":
                # The last
                color = COLOR_PALETTE[-1]
            elem.style = {"fill": color}
            # Move to holes group
            holes_group.append(elem)

        #
        # Holes are moved to a separate "holes" group. Combine all
        # elements back per page (now without holes).
        #
        path_cmds = []
        for old_group in nested_groups:
            group = self.svg.getElementById(old_group.get_id())
            if group is None:
                assert False, "Group can't be found! Assert!"

            combine_elems = []
            for elem in group:
                combine_elems.append(elem)

            # Combine paths per group
            path_cmds.append((combine_elems, "comb"))

        # Do combine paths
        self.run_pathops(path_cmds)

        #
        # Reparent all elements, get rid of nested groups
        #
        for old_group in nested_groups:
            group = self.svg.getElementById(old_group.get_id())
            if group is None:
                assert False, "Group can't be found! Assert!"

            for elem in group:
                # Reparent elem
                group.getparent().append(elem)

            # Delete nested group
            group.delete()


        #
        # Find difference between holes and everything else.
        # This makes holes correct.
        #

        # Redefine holes group object because svg was changed
        holes_group = self.svg.getElementById(holes_group.get_id())
        if holes_group is None:
            assert False, "Holes group can't be found! Assert!"

        # Hole differences
        path_cmds = []
        for hole in holes_group:
            page_number = hole.get_id().split("-")[0]
            if page_number not in dup_elems_map:
                assert False, "Page number is not found in dup map! Assert!"

            id_str = dup_elems_map[page_number]
            elem = self.svg.getElementById(id_str)
            if elem is None:
                assert False, "Dup elem can't be found! Assert!"

            path_cmds.append(((hole, elem), "diff"))

        # Do hole difference
        self.run_pathops(path_cmds)

    def effect(self):
        # Check that elements have been selected
        if not self.svg.selection:
            assert False, "Please select objects!"

        pages = self.svg.namedview.get_pages()
        if len(pages) == 0:
            # By default there are no pages at all
            pages = [Page.new(self.svg.viewbox_width, self.svg.viewbox_height, 0, 0)]

        overall_bbox = BoundingBox()

        for page in pages:
            bbox = BoundingBox((page.x, page.x + page.width),
                               (page.y, page.y + page.height))

            overall_bbox.x.minimum = min(overall_bbox.x.minimum,
                                         bbox.x.minimum)
            overall_bbox.x.maximum = max(overall_bbox.x.maximum,
                                         bbox.x.maximum)
            overall_bbox.y.minimum = min(overall_bbox.y.minimum,
                                         bbox.y.minimum)
            overall_bbox.y.maximum = max(overall_bbox.y.maximum,
                                         bbox.y.maximum)

        res = self.calculate_poster_size()
        if res is None:
            return

        sheet_size, slice_rect_size, sheets_n, margin, scale = res

        if len(pages) == 1:
            # Need to create the first page, otherwise inkscape goes mad
            self.svg.namedview.add(pages[0])

        # Start position of our poster
        x_pos = overall_bbox.x.minimum
        y_pos = overall_bbox.y.maximum

        path_cmds = []

        # The whole image selection
        sel_bbox = self.svg.selection.bounding_box()

        # Posterbator layer
        layer = self.svg.add(inkex.Layer.new("Posterbator"))
        layer_id = layer.get_id()

        # Create groups for each selection for easy manipulation
        # in inkscape gui
        groups = []
        for elem in self.svg.selection.filter():
            groups.append(Group())

        # Create pages
        pages = []
        for j in range(0, int(sheets_n[1])):
            y = y_pos + j * sheet_size[1]
            for i in range(0, int(sheets_n[0])):
                x = x_pos + i * sheet_size[0]
                # Create corresponding page
                page = self.svg.namedview.new_page(x=str(x), y=str(y),
                                                   width=str(sheet_size[0]),
                                                   height=str(sheet_size[1]))
                pages.append(page)

                # For each page duplicate the whole selection, create a
                # rectangle for intersection (slicing)
                for ind, elem in enumerate(self.svg.selection.filter()):
                    dup = elem.duplicate()
                    bbox = dup.bounding_box()

                    # Slicing rectangle
                    rect = self.svg.add(Rectangle.new(
                        left=sel_bbox.x.minimum + i * slice_rect_size[0],
                        top=sel_bbox.y.minimum + j * slice_rect_size[1],
                        width=slice_rect_size[0],
                        height=slice_rect_size[1]))

                    # XXX Should be called at least once before path
                    # XXX operation, otherwise inkscape assigns different
                    # XXX ids (please, tell me why).
                    rect.get_id()

                    # Store page index, page and group as a payload
                    payload = ((i, j), page, groups[ind])
                    path_cmds.append(((dup, rect), "inter", payload))

        # Do slice as intersection path operations
        self.run_pathops(path_cmds)

        # Clear selection
        self.svg.selection.set()

        # Go over each sliced element and add to selection
        selections = []
        for cmd in path_cmds:
            elems, _, (page_idx, page, group) = cmd
            elem = self.svg.getElementById(elems[0].get_id())
            if elem == None:
                # Some of the elements can be missing, which means
                # no intersection with the provided slicing rectangle,
                # which is ok
                continue

            self.svg.selection.add(elem)
            selections.append((elem, page_idx, page, group))

        # Get bounding box of all sliced elements
        sel_bbox = self.svg.selection.bounding_box()

        # Transition of the scaled image to the first page position
        dx = -sel_bbox.x.minimum * scale + x_pos
        dy = -sel_bbox.y.minimum * scale + y_pos

        # Create group for the current layer
        layer = self.svg.getElementById(layer_id)
        if layer is None:
            assert False, "Layer can't be found! Assert!"

        for i, group in enumerate(groups):
            layer.append(group)
            # XXX Should be called at least once before path
            # XXX operation, otherwise inkscape assigns different
            # XXX ids (please, tell me why).
            group.get_id()
            # From backwards, in UI last element is on top
            ind = len(groups) - i
            group.label = "%d-group" % ind
            group.style = {"fill": COLOR_PALETTE[ind - 1]}

        # Create separated holes group
        if self.options.output_holes_group == "true":
            # Create holes group
            holes_group = Group()
            holes_group.label = "holes"
            layer.append(holes_group)

        # Create helper page frames for easy orientation in multi-layers
        # output poster results
        if self.options.output_page_frames == "true":
            frames_group = Group()
            frames_group.label = "frames"
            layer.append(frames_group)

        # Create group for pages numbers
        if self.options.output_page_numbers == "true":
            numbers_group = Group()
            numbers_group.label = "numbers"
            layer.append(numbers_group)

        # Scale and translate each sliced element
        for selection in selections:
            elem, page_idx, page, group = selection
            bbox = elem.bounding_box()

            id_fmt = get_page_number_str(page_idx) + "-%s"

            # Don't forget already pre-set transform
            trans = elem.get("transform")
            elem.set("transform", "translate(%f,%f) scale(%f) %s" %
                     (dx + margin + margin * page_idx[0] * 2,
                      dy + margin + margin * page_idx[1] * 2,
                      scale, trans))
            elem.set_id(id_fmt % elem.get_id())
            if self.options.output_use_palette == "true":
                elem.style = group.style
            # Add element to a group
            group.append(elem)

            if self.options.output_page_numbers == "true":
                # Create page number text
                text_style = Style({
                    "stroke": "none",
                    "font-size": "20px",
                    "fill": "black",
                    "font-family": "arial",
                    "text-anchor": "start",
                })
                text_attribs = {"x": str(page.x + page.width - 30),
                                "y": str(page.y + page.height - 10)}
                text = numbers_group.add(TextElement(**text_attribs))
                text.style = text_style
                text.text = get_page_number_str(page_idx)
                text.set_id(id_fmt % text.get_id())

            if self.options.output_page_frames == "true":
                rect = frames_group.add(Rectangle(x=str(page.x + margin),
                                                  y=str(page.y + margin),
                                                  width=str(page.width - 2 * margin),
                                                  height=str(page.height - 2 * margin)))
                rect.style = {"stroke": "#000000",
                              "stroke-width": "4px",
                              "fill": "none"}
                rect.set_id(id_fmt % rect.get_id())

        # Separate holes
        if self.options.output_holes_group == "true":
            group_ids = [group.get_id() for group in groups]
            holes_group_id = holes_group.get_id()
            self.separate_holes(group_ids, holes_group_id)


if __name__ == "__main__":
    Posterbator().run()
