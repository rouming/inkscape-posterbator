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
Posterbation
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

def rm_file(tempfile):
    try:
        os.remove(tempfile)
    except Exception:  # pylint: disable=broad-except
        pass

def get_inkscape_version():
    ink = inkex.command.INKSCAPE_EXECUTABLE_NAME
    try: # needed prior to 1.1
        ink_version = inkex.command.call(ink, '--version').decode("utf-8")
    except AttributeError: # needed starting from 1.1
        ink_version = inkex.command.call(ink, '--version')

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

class Posterbation(inkex.EffectExtension):
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

    # ----- workaround to fix Effect() performance with large selections


    def run_pathops(self, svgfile, cmds, dry_run=False):
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
                "desel": "select-clear",
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
        inkversion = get_inkscape_version()
        actions_list = []
        duplicate_command = ACTIONS[inkversion]['dup']
        deselect_command = ACTIONS[inkversion]['desel']
        save_command = ACTIONS[inkversion]['save']

        for cmd in cmds:
            path_op_command = ACTIONS[inkversion][cmd[2]]
            actions_list.append("select-by-id:" + cmd[0].get_id())
            actions_list.append("select-by-id:" + cmd[1].get_id())
            actions_list.append(path_op_command)
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
        # process command list
        if dry_run:
            inkex.utils.debug(" ".join(["inkscape", extra_param,
                                        "--actions=" + "\"" + actions + "\"",
                                        svgfile, f"(using Inkscape {inkversion})"]))
        else:
            if extra_param != "":
                inkex.command.inkscape(svgfile, extra_param, actions=actions)
            else:
                inkex.command.inkscape(svgfile, actions=actions)

    def calculate_poster_size(self):
        # Obtain sheet size
        sheet_size = ()
        if self.options.sheet_size == "A4":
            sheet_size = (210, 297)
        else:
            inkex.errormsg(_("Incorrect sheet size!"))
            return None

        # Obtain sheet orientation
        if self.options.sheet_orientation == "landscape":
            # Swap width and height
            sheet_size = (sheet_size[1], sheet_size[0])

        # Validate and obtain sheets number
        sheets_n = float(self.options.output_sheets_number)
        if sheets_n < 1 or sheets_n > 10:
            inkex.errormsg(_("Incorrect sheets number!"))
            return None

        # Validate and obtain margin
        margin = float(self.options.margin)
        if margin < 0 or margin > 50:
            inkex.errormsg(_("Incorrect margin!"))
            return None

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

    def effect(self):
        # Check that elements have been selected
        if not self.svg.selection:
            inkex.errormsg(_("Please select objects!"))
            return

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

        slicing_cmds = []

        # The whole image selection
        sel_bbox = self.svg.selection.bounding_box()

        # Create groups for each selection for easy manipulation
        # in inkscape gui
        groups = {}
        for elem in self.svg.selection.filter():
            groups[elem.get_id()] = Group()

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
                for elem in self.svg.selection.filter():
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

                    group = groups[elem.get_id()]
                    if group is None:
                        inkex.errormsg(_("Group can't be found! Assert!"))
                        return

                    # Save elements, operation, page index, page and group
                    slicing_cmds.append((dup, rect, "inter", (i, j), page, group))

        # Save current state to a temp file before proceeding with
        # path operations in order run_pathops() gets all the changes
        tempfile = self.options.input_file + "-pathops.svg"
        temp = open(tempfile, "wb")
        self.save(temp)
        temp.close()

        self.run_pathops(tempfile, slicing_cmds)

        # replace current document with content of temp copy file
        self.document = inkex.load_svg(tempfile)
        rm_file(tempfile)
        # update self.svg
        self.svg = self.document.getroot()
        self.update_tagrefs()

        # Clear selection
        self.svg.selection.set()

        # Go over each sliced element and add to selection
        selections = []
        for cmd in slicing_cmds:
            dup_elem, _, _, page_idx, page, group = cmd
            elem = self.svg.getElementById(dup_elem.get_id())
            if elem == None:
                # Some of the elements can be missing, which is ok
                continue

            self.svg.selection.add(elem)
            selections.append((elem, page_idx, page, group))

        # Get bounding box of all sliced elements
        sel_bbox = self.svg.selection.bounding_box()

        # Transition of the scaled image to the first page position
        dx = -sel_bbox.x.minimum * scale + x_pos
        dy = -sel_bbox.y.minimum * scale + y_pos

        # Create group for the current layer
        layer = self.svg.get_current_layer()
        for group in groups.values():
            layer.append(group)


        # Create helper page frames for easy orientation in multi-layers
        # output poster results
        if self.options.output_page_frames == "true":
            group = Group()
            layer.append(group)

            for page in pages:
                rect = group.add(Rectangle(x=str(page.x + margin),
                                           y=str(page.y + margin),
                                           width=str(page.width - 2 * margin),
                                           height=str(page.height - 2 * margin)))
                rect.style = {"stroke": "#000000",
                              "stroke-width": "4px",
                              "fill": "none"}

        # Create group for pages numbers
        if self.options.output_page_numbers == "true":
            numbers_group = Group()
            layer.append(numbers_group)

        # Scale and translate each sliced element
        for selection in selections:
            elem, page_idx, page, group = selection
            bbox = elem.bounding_box()

            # Don't forget already pre-set transform
            trans = elem.get("transform")
            elem.set("transform", "translate(%f,%f) scale(%f) %s" %
                     (dx + margin + margin * page_idx[0] * 2,
                      dy + margin + margin * page_idx[1] * 2,
                      scale, trans))
            # Add element to a group
            group.append(elem)

            if self.options.output_page_numbers == "true":
                # Create page number text
                text_style = Style({
                    "stroke": "white",
                    "font-size": "20px",
                    "fill": "black",
                    "font-family": "arial",
                    "text-anchor": "start",
                })
                text_attribs = {"x": str(page.x + page.width - 30),
                                "y": str(page.y + page.height - 10)}
                text = numbers_group.add(TextElement(**text_attribs))
                text.style = text_style
                text.text = "%s%d" % (chr(65 + page_idx[0]), page_idx[1] + 1)


if __name__ == "__main__":
    Posterbation().run()
