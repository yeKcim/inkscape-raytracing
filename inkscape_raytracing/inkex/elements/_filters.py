# -*- coding: utf-8 -*-
#
# Copyright (c) 2020 Martin Owens <doctormo@gmail.com>
#                    Sergei Izmailov <sergei.a.izmailov@gmail.com>
#                    Thomas Holder <thomas.holder@schrodinger.com>
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
# pylint: disable=arguments-differ
"""
Element interface for patterns, filters, gradients and path effects.
"""

from lxml import etree
from copy import deepcopy

from ..transforms import Transform
from ..units import convert_unit

from ..styles import Style

from ._utils import addNS
from ._base import BaseElement


from typing import overload, Iterable, List, Tuple, Union, Optional, TYPE_CHECKING  # pylint: disable=unused-import

if TYPE_CHECKING:
    from inkex import SvgDocumentElement

class Filter(BaseElement):
    """A filter (usually in defs)"""
    tag_name = 'filter'

    def add_primitive(self, fe_type, **args):
        """Create a filter primitive with the given arguments"""
        elem = etree.SubElement(self, addNS(fe_type, 'svg'))
        elem.update(**args)
        return elem

    class Primitive(BaseElement):
        pass

    class Blend(Primitive):
        tag_name = 'feBlend'

    class ColorMatrix(Primitive):
        tag_name = 'feColorMatrix'

    class ComponentTransfer(Primitive):
        tag_name = 'feComponentTransfer'

    class Composite(Primitive):
        tag_name = 'feComposite'

    class ConvolveMatrix(Primitive):
        tag_name = 'feConvolveMatrix'

    class DiffuseLighting(Primitive):
        tag_name = 'feDiffuseLighting'

    class DisplacementMap(Primitive):
        tag_name = 'feDisplacementMap'

    class Flood(Primitive):
        tag_name = 'feFlood'

    class GaussianBlur(Primitive):
        tag_name = 'feGaussianBlur'

    class Image(Primitive):
        tag_name = 'feImage'

    class Merge(Primitive):
        tag_name = 'feMerge'

    class Morphology(Primitive):
        tag_name = 'feMorphology'

    class Offset(Primitive):
        tag_name = 'feOffset'

    class SpecularLighting(Primitive):
        tag_name = 'feSpecularLighting'

    class Tile(Primitive):
        tag_name = 'feTile'

    class Turbulence(Primitive):
        tag_name = 'feTurbulence'


class Stop(BaseElement):
    tag_name = 'stop'

    @property
    def offset(self):
        # type: () -> float
        return self.get('offset')

    @offset.setter
    def offset(self, number):
        self.set('offset', number)

    def interpolate(self, other, fraction):
        from ..tween import StopInterpolator
        return StopInterpolator(self, other).interpolate(fraction)


class Pattern(BaseElement):
    """Pattern element which is used in the def to control repeating fills"""
    tag_name = 'pattern'
    WRAPPED_ATTRS = BaseElement.WRAPPED_ATTRS + (('patternTransform', Transform),)


class Gradient(BaseElement):
    """A gradient instruction usually in the defs"""
    WRAPPED_ATTRS = BaseElement.WRAPPED_ATTRS + (('gradientTransform', Transform),)

    orientation_attributes = () # type: Tuple[str, ...]

    @property
    def stops(self):
        """Return an ordered list of own or linked stop nodes"""
        gradcolor = self.href if isinstance(self.href, (LinearGradient, RadialGradient)) else self
        return sorted([child for child in gradcolor if isinstance(child, Stop)]
                      , key=lambda x: float(x.offset))

    @property
    def stop_offsets(self):
        # type: () -> List[float]
        """Return a list of own or linked stop offsets"""
        return [child.offset for child in self.stops]

    @property
    def stop_styles(self): # type: () -> List[Style]
        """Return a list of own or linked offset styles"""
        return [child.style for child in self.stops]

    def remove_orientation(self):
        """Remove all orientation attributes from this element"""
        for attr in self.orientation_attributes:
            self.pop(attr)
    def interpolate(self, other, fraction, svg=None): # type: (LinearGradient, float, SvgDocumentElement) -> LinearGradient
        """Interpolate with another gradient."""
        from ..tween import GradientInterpolator
        return GradientInterpolator(self, other, svg).interpolate(fraction)

    def stops_and_orientation(self):
        """Return a copy of all the stops in this gradient"""
        stops = self.copy()
        stops.remove_orientation()
        orientation = self.copy()
        orientation.remove_all(Stop)
        return stops, orientation


class LinearGradient(Gradient):
    tag_name = 'linearGradient'
    orientation_attributes = ('x1', 'y1', 'x2', 'y2')

    def apply_transform(self): # type: () -> None
       """Apply transform to orientation points and set it to identity."""
       trans = self.pop('gradientTransform')
       p1 = (self.unittouu(self.get('x1')), self.unittouu(self.get('y1')))
       p2 = (self.unittouu(self.get('x2')), self.unittouu(self.get('y2')))
       p1t = trans.apply_to_point(p1)
       p2t = trans.apply_to_point(p2)
       self.update(
            x1=self.unittouu(p1t[0]),
            y1=self.unittouu(p1t[1]),
            x2=self.unittouu(p2t[0]),
            y2=self.unittouu(p2t[1]))


class RadialGradient(Gradient):
    tag_name = 'radialGradient'
    orientation_attributes = ('cx', 'cy', 'fx', 'fy', 'r')

    def apply_transform(self): # type: () -> None
       """Apply transform to orientation points and set it to identity."""
       trans = self.pop('gradientTransform')
       p1 = (self.unittouu(self.get('cx')), self.unittouu(self.get('cy')))
       p2 = (self.unittouu(self.get('fx')), self.unittouu(self.get('fy')))
       p1t = trans.apply_to_point(p1)
       p2t = trans.apply_to_point(p2)
       self.update(
            cx=self.unittouu(p1t[0]),
            cy=self.unittouu(p1t[1]),
            fx=self.unittouu(p2t[0]),
            fy=self.unittouu(p2t[1]))

class PathEffect(BaseElement):
    """Inkscape LPE element"""
    tag_name = 'inkscape:path-effect'


class MeshGradient(Gradient):
    """Usable MeshGradient XML base class"""
    tag_name = 'meshgradient'

    @classmethod
    def new_mesh(cls, pos=None, rows=1, cols=1, autocollect=True):
        """Return skeleton of 1x1 meshgradient definition."""
        # initial point
        if pos is None or len(pos) != 2:
            pos = [0.0, 0.0]
        # create nested elements for rows x cols mesh
        meshgradient = cls()
        for _ in range(rows):
            meshrow = meshgradient.add(MeshRow())
            for _ in range(cols):
                meshrow.append(MeshPatch())
        # set meshgradient attributes
        meshgradient.set('gradientUnits', 'userSpaceOnUse')
        meshgradient.set('x', pos[0])
        meshgradient.set('y', pos[1])
        if autocollect:
            meshgradient.set('inkscape:collect', 'always')
        return meshgradient


class MeshRow(BaseElement):
    """Each row of a mesh gradient"""
    tag_name = 'meshrow'

class MeshPatch(BaseElement):
    """Each column or 'patch' in a mesh gradient"""
    tag_name = 'meshpatch'

    def stops(self, edges, colors):
        """Add or edit meshpatch stops with path and stop-color."""
        # iterate stops based on number of edges (path data)
        for i, edge in enumerate(edges):
            if i < len(self):
                stop = self[i]
            else:
                stop = self.add(Stop())

            # set edge path data
            stop.set('path', str(edge))
            # set stop color
            stop.style['stop-color'] = str(colors[i % 2])
