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
Provide extra utility to each svg element type specific to its type.

This is useful for having a common interface for each element which can
give path, transform, and property access easily.
"""

from collections import defaultdict
from copy import deepcopy
from lxml import etree

from ..paths import Path
from ..styles import Style, Classes
from ..transforms import Transform, BoundingBox
from ..utils import FragmentError
from ..units import convert_unit, render_unit, parse_unit
from ._utils import ChildToProperty, NSS, addNS, removeNS, splitNS
from ..properties import BaseStyleValue, all_properties

#from ..deprecated import DeprecatedShapeElementMixin

from typing import overload, DefaultDict, Type, Any, List, Tuple, Union, Optional  # pylint: disable=unused-import

class NodeBasedLookup(etree.PythonElementClassLookup):
    """
    We choose what kind of Elements we should return for each element, providing useful
    SVG based API to our extensions system.
    """
    # (ns,tag) -> list(cls) ; ascending priority
    lookup_table = defaultdict(list) # type: DefaultDict[str, List[Any]]

    @classmethod
    def register_class(cls, klass):
        """Register the given class using it's attached tag name"""
        cls.lookup_table[splitNS(klass.tag_name)].append(klass)

    @classmethod
    def find_class(cls, xpath):
        """Find the class for this type of element defined by an xpath"""
        if isinstance(xpath, type):
            return xpath
        for cls in cls.lookup_table[splitNS(xpath.split('/')[-1])]:
            # TODO: We could create a apply the xpath attrs to the test element
            # to narrow the search, but this does everything we need right now.
            test_element = cls()
            if cls._is_class_element(test_element):
                return cls
        raise KeyError(f"Could not find svg tag for '{xpath}'")

    def lookup(self, doc, element): # pylint: disable=unused-argument
        """Lookup called by lxml when assigning elements their object class"""
        try:
            for cls in reversed(self.lookup_table[splitNS(element.tag)]):
                if cls._is_class_element(element): # pylint: disable=protected-access
                    return cls
        except TypeError:
            # Handle non-element proxies case
            # The documentation implies that it's not possible
            # Didn't found a reliable way to check whether proxy corresponds to element or not
            # Look like lxml issue to me.
            # The troubling element is "<!--Comment-->"
            return None
        return BaseElement


SVG_PARSER = etree.XMLParser(huge_tree=True, strip_cdata=False)
SVG_PARSER.set_element_class_lookup(NodeBasedLookup())

def load_svg(stream):
    """Load SVG file using the SVG_PARSER"""
    if (isinstance(stream, str) and stream.lstrip().startswith('<'))\
      or (isinstance(stream, bytes) and stream.lstrip().startswith(b'<')):
        return etree.ElementTree(etree.fromstring(stream, parser=SVG_PARSER))
    return etree.parse(stream, parser=SVG_PARSER)

class BaseElement(etree.ElementBase):
    """Provide automatic namespaces to all calls"""
    def __init_subclass__(cls):
        if cls.tag_name:
            NodeBasedLookup.register_class(cls)

    @classmethod
    def _is_class_element(cls, el):  # type: (etree.Element) -> bool
        """Hook to do more restrictive check in addition to (ns,tag) match"""
        return True

    tag_name = ''

    @property
    def TAG(self): # pylint: disable=invalid-name
        """Return the tag_name without NS"""
        if not self.tag_name:
            return removeNS(super().tag)[-1]
        return removeNS(self.tag_name)[-1]

    @classmethod
    def new(cls, *children, **attrs):
        """Create a new element, converting attrs values to strings."""
        obj = cls(*children)
        obj.update(**attrs)
        return obj

    NAMESPACE = property(lambda self: splitNS(self.tag_name)[0])
    PARSER = SVG_PARSER
    WRAPPED_ATTRS = (
        # (prop_name, [optional: attr_name], cls)
        ('transform', Transform),
        ('style', Style),
        ('classes', 'class', Classes),
    ) # type: Tuple[Tuple[Any, ...], ...]

    # We do this because python2 and python3 have different ways
    # of combining two dictionaries that are incompatible.
    # This allows us to update these with inheritance.
    @property
    def wrapped_attrs(self):
        """Map attributes to property name and wrapper class"""
        return dict([(row[-2], (row[0], row[-1])) for row in self.WRAPPED_ATTRS])

    @property
    def wrapped_props(self):
        """Map properties to attribute name and wrapper class"""
        return dict([(row[0], (row[-2], row[-1])) for row in self.WRAPPED_ATTRS])

    typename = property(lambda self: type(self).__name__)
    xml_path = property(lambda self: self.getroottree().getpath(self))
    desc = ChildToProperty("svg:desc", prepend=True)
    title = ChildToProperty("svg:title", prepend=True)

    def __getattr__(self, name):
        """Get the attribute, but load it if it is not available yet"""
        if name in self.wrapped_props:
            (attr, cls) = self.wrapped_props[name]
            # The reason we do this here and not in _init is because lxml
            # is inconsistant about when elements are initialised.
            # So we make this a lazy property.
            def _set_attr(new_item):
                if new_item:
                    self.set(attr, str(new_item))
                else:
                    self.attrib.pop(attr, None) # pylint: disable=no-member
                    
            # pylint: disable=no-member
            value = cls(self.attrib.get(attr, None), callback=_set_attr)
            if name == "style":
                value.element = self
            setattr(self, name, value)
            return value
        raise AttributeError(f"Can't find attribute {self.typename}.{name}")

    def __setattr__(self, name, value):
        """Set the attribute, update it if needed"""
        if name in self.wrapped_props:
            (attr, cls) = self.wrapped_props[name]
            # Don't call self.set or self.get (infinate loop)
            if value:
                if not isinstance(value, cls):
                    value = cls(value)
                self.attrib[attr] = str(value)
            else:
                self.attrib.pop(attr, None) # pylint: disable=no-member
        else:
            super().__setattr__(name, value)

    def get(self, attr, default=None):
        """Get element attribute named, with addNS support."""
        if attr in self.wrapped_attrs:
            (prop, _) = self.wrapped_attrs[attr]
            value = getattr(self, prop, None)
            # We check the boolean nature of the value, because empty
            # transformations and style attributes are equiv to not-existing
            ret = str(value) if value else (default or None)
            return ret
        return super().get(addNS(attr), default)

    def set(self, attr, value):
        """Set element attribute named, with addNS support"""
        if attr in self.wrapped_attrs:
            # Always keep the local wrapped class up to date.
            (prop, cls) = self.wrapped_attrs[attr]
            setattr(self, prop, cls(value))
            value = getattr(self, prop)
            if not value:
                return
        if value is None:
            self.attrib.pop(addNS(attr), None) # pylint: disable=no-member
        else:
            value = str(value)
            super().set(addNS(attr), value)

    def update(self, **kwargs):
        """
        Update element attributes using keyword arguments

        Note: double underscore is used as namespace separator,
        i.e. "namespace__attr" argument name will be treated as "namespace:attr"

        :param kwargs: dict with name=value pairs
        :return: self
        """
        for name, value in kwargs.items():
            self.set(name, value)
        return self

    def pop(self, attr, default=None):
        """Delete/remove the element attribute named, with addNS support."""
        if attr in self.wrapped_attrs:
            # Always keep the local wrapped class up to date.
            (prop, cls) = self.wrapped_attrs[attr]
            value = getattr(self, prop)
            setattr(self, prop, cls(None))
            return value
        return self.attrib.pop(addNS(attr), default) # pylint: disable=no-member

    def add(self, *children):
        """
        Like append, but will do multiple children and will return
        children or only child
        """
        for child in children:
            self.append(child)
        return children if len(children) != 1 else children[0]

    def tostring(self):
        """Return this element as it would appear in an svg document"""
        # This kind of hack is pure maddness, but etree provides very little
        # in the way of fragment printing, prefering to always output valid xml
        from ..base import SvgOutputMixin
        svg = SvgOutputMixin.get_template(width=0, height=0).getroot()
        svg.append(self.copy())
        return svg.tostring().split(b'>\n    ', 1)[-1][:-6]

    def set_random_id(self, prefix=None, size=4, backlinks=False):
        """Sets the id attribute if it is not already set."""
        prefix = str(self) if prefix is None else prefix
        self.set_id(self.root.get_unique_id(prefix, size=size), backlinks=backlinks)

    def set_random_ids(self, prefix=None, levels=-1, backlinks=False):
        """Same as set_random_id, but will apply also to children"""
        self.set_random_id(prefix=prefix, backlinks=backlinks)
        if levels != 0:
            for child in self:
                if hasattr(child, 'set_random_ids'):
                    child.set_random_ids(prefix=prefix, levels=levels-1, backlinks=backlinks)

    eid = property(lambda self: self.get_id())
    def get_id(self, as_url=0):
        """Get the id for the element, will set a new unique id if not set.

        as_url - If set to 1, returns #{id} as a string
                 If set to 2, returns url(#{id}) as a string
        """
        if 'id' not in self.attrib:
            self.set_random_id(self.TAG)
        eid = self.get('id')
        if as_url > 0:
            eid = '#' + eid
        if as_url > 1:
            eid = f'url({eid})'
        return eid

    def set_id(self, new_id, backlinks=False):
        """Set the id and update backlinks to xlink and style urls if needed"""
        old_id = self.get('id', None)
        self.set('id', new_id)
        if backlinks and old_id:
            for elem in self.root.getElementsByHref(old_id):
                elem.href = self
            for elem in self.root.getElementsByStyleUrl(old_id):
                elem.style.update_urls(old_id, new_id)

    @property
    def root(self):
        """Get the root document element from any element descendent"""
        if self.getparent() is not None:
            return self.getparent().root
        from ._svg import SvgDocumentElement
        if not isinstance(self, SvgDocumentElement):
            raise FragmentError("Element fragment does not have a document root!")
        return self

    def get_or_create(self, xpath, nodeclass=None, prepend=False):
        """Get or create the given xpath, pre/append new node if not found."""
        node = self.findone(xpath)
        if node is None:
            if nodeclass is None:
                nodeclass = NodeBasedLookup.find_class(xpath)
            node = nodeclass()
            if prepend:
                self.insert(0, node)
            else:
                self.append(node)
        return node

    def descendants(self):
        """Walks the element tree and yields all elements, parent first"""
        from ._selected import ElementList
        return ElementList(self.root, self._descendants())

    def _descendants(self):
        yield self
        for child in self:
            if hasattr(child, '_descendants'):
                yield from child._descendants() # pylint: disable=protected-access

    def ancestors(self, elem=None, stop_at=()):
        """
        Walk the parents and yield all the ancestor elements, parent first

        If elem is provided, it will stop at the last common ancestor.
        If stop_at is provided, it will stop at the first parent that is in this list.
        """
        from ._selected import ElementList
        return ElementList(self.root, self._ancestors(elem=elem, stop_at=stop_at))

    def _ancestors(self, elem, stop_at):
        if isinstance(elem, BaseElement):
            stop_at = list(elem.ancestors())
        parent = self.getparent()
        if parent is not None:
            yield parent
            if parent not in stop_at:
                yield from parent._ancestors(elem=elem, stop_at=stop_at) # pylint: disable=protected-access

    def backlinks(self, *types):
        """Get elements which link back to this element, like ancestors but via xlinks"""
        if not types or isinstance(self, types):
            yield self
        my_id = self.get('id')
        if my_id is not None:
            elems = list(self.root.getElementsByHref(my_id)) \
                  + list(self.root.getElementsByStyleUrl(my_id))
            for elem in elems:
                if hasattr(elem, 'backlinks'):
                    for child in elem.backlinks(*types):
                        yield child

    def xpath(self, pattern, namespaces=NSS):  # pylint: disable=dangerous-default-value
        """Wrap xpath call and add svg namespaces"""
        return super().xpath(pattern, namespaces=namespaces)

    def findall(self, pattern, namespaces=NSS):  # pylint: disable=dangerous-default-value
        """Wrap findall call and add svg namespaces"""
        return super().findall(pattern, namespaces=namespaces)

    def findone(self, xpath):
        """Gets a single element from the given xpath or returns None"""
        el_list = self.xpath(xpath)
        return el_list[0] if el_list else None

    def delete(self):
        """Delete this node from it's parent node"""
        if self.getparent() is not None:
            self.getparent().remove(self)

    def remove_all(self, *types):
        """Remove all children or child types"""
        types = tuple(NodeBasedLookup.find_class(t) for t in types)
        for child in self:
            if not types or isinstance(child, types):
                self.remove(child)

    def replace_with(self, elem):
        """Replace this element with the given element"""
        self.addnext(elem)
        if not elem.get('id') and self.get('id'):
            elem.set('id', self.get('id'))
        if not elem.label and self.label:
            elem.label = self.label
        self.delete()
        return elem

    def copy(self):
        """Make a copy of the element and return it"""
        elem = deepcopy(self)
        elem.set('id', None)
        return elem

    def duplicate(self):
        """Like copy(), but the copy stays in the tree and sets a random id"""
        elem = self.copy()
        self.addnext(elem)
        elem.set_random_id()
        return elem

    def __str__(self):
        # We would do more here, but lxml is VERY unpleseant when it comes to
        # namespaces, basically over printing details and providing no
        # supression mechanisms to turn off xml's over engineering.
        return str(self.tag).split('}')[-1]

    @property
    def href(self):
        """Returns the referred-to element if available"""
        ref = self.get('xlink:href')
        if not ref:
            return None
        return self.root.getElementById(ref.strip('#'))

    @href.setter
    def href(self, elem):
        """Set the href object"""
        if isinstance(elem, BaseElement):
            elem = elem.get_id()
        self.set('xlink:href', '#' + elem)

    @property
    def label(self):
        """Returns the inkscape label"""
        return self.get('inkscape:label', None)

    label = label.setter(lambda self, value: self.set('inkscape:label', str(value))) # type: ignore

    def is_sensitive(self):
        """Return true if this element is sensitive in inkscape"""
        return self.get('sodipodi:insensitive', None) != 'true'

    def set_sensitive(self, sensitive=True):
        """Set the sensitivity of the element/layer"""
        # Sensitive requires None instead of 'false'
        self.set('sodipodi:insensitive', ['true', None][sensitive])

    @property
    def unit(self):
        """Return the unit being used by the owning document, cached"""
        try:
            return self.root.unit
        except FragmentError:
            return 'px' # Don't cache.

    @staticmethod
    def uutounit(value, to_unit='px'):
        """Convert a value given in user units (px) the given unit type"""
        return convert_unit(value, to_unit)

    @staticmethod
    def unittouu(value):
        """Convert a length value into user units (px)"""
        return convert_unit(value, "px")

    def unit_to_viewport(self, value, unit="px"):
        """Converts a length value to viewport units, as defined by the width/height
        element on the root"""
        return self.uutounit(self.unittouu(value) * self.root.equivalent_transform_scale, unit)

    def viewport_to_unit(self, value, unit="px"):
        """Converts a length given on the viewport to the specified unit in the user
        coordinate system"""
        return self.uutounit(self.unittouu(value) / self.root.equivalent_transform_scale, unit)

    def add_unit(self, value):
        """Add document unit when no unit is specified in the string """
        return render_unit(value, self.unit)

    def cascaded_style(self):
        """Returns the cascaded style of an element (all rules that apply the element itself),
        based on the stylesheets, the presentation attributes and the inline style using the
        respective specificity of the style

        see https://www.w3.org/TR/CSS22/cascade.html#cascading-order

        Returns:
            Style: the cascaded style
        """
        return Style.cascaded_style(self)

    def specified_style(self):
        """Returns the specified style of an element, i.e. the cascaded style + inheritance,
        see https://www.w3.org/TR/CSS22/cascade.html#specified-value

        Returns:
            Style: the specified style
        """
        return Style.specified_style(self)

    def presentation_style(self):
        """Return presentation attributes of an element as style"""
        style = Style()
        for key in self.keys():
            if key in all_properties and all_properties[key][2]:
                style[key] = BaseStyleValue.factory(declaration=key + ": " + self.attrib[key])
        return style
    
    def composed_transform(self, other=None):
        """Calculate every transform down to the other element
          if none specified the transform is to the root document element"""
        parent = self.getparent()
        if parent is not None and isinstance(parent, BaseElement):
            return parent.composed_transform() * self.transform
        return self.transform

class ShapeElement(BaseElement):
    """Elements which have a visible representation on the canvas"""
    @property
    def path(self):
        """Gets the outline or path of the element, this may be a simple bounding box"""
        return Path(self.get_path())

    @path.setter
    def path(self, path):
        self.set_path(path)

    @property
    def clip(self):
        """Gets the clip path element (if any)"""
        ref = self.get('clip-path')
        if not ref:
            return None
        return self.root.getElementById(ref)

    @clip.setter
    def clip(self, elem):
        self.set('clip-path', elem.get_id(as_url=2))

    def get_path(self):
        """Generate a path for this object which can inform the bounding box"""
        raise NotImplementedError(f"Path should be provided by svg elem {self.typename}.")

    def set_path(self, path):
        """Set the path for this object (if possible)"""
        raise AttributeError(
            f"Path can not be set on this element: {self.typename} <- {path}.")

    def to_path_element(self):
        """Replace this element with a path element"""
        from ._polygons import PathElement
        elem = PathElement()
        elem.path = self.path
        elem.style = self.effective_style()
        elem.transform = self.transform
        return elem

    def effective_style(self):
        """Without parent styles, what is the effective style is"""
        return self.style

    def bounding_box(self, transform=None):
        # type: (Optional[Transform]) -> Optional[BoundingBox]
        """BoundingBox of the shape (adjusted for its clip path if applicable)"""
        shape_box = self.shape_box(transform)
        clip = self.clip
        if clip is None or shape_box is None:
            return shape_box
        return shape_box & clip.bounding_box(Transform(transform) * self.transform)

    def shape_box(self, transform=None):
        # type: (Optional[Transform]) -> Optional[BoundingBox]
        """BoundingBox of the unclipped shape"""
        path = self.path.to_absolute()
        if transform is True:
            path = path.transform(self.composed_transform())
        else:
            path = path.transform(self.transform)
            if transform:  # apply extra transformation
                path = path.transform(transform)
        return path.bounding_box()

    def is_visible(self):
        """Returns false if the css says this object is invisible"""
        if self.style.get('display', '') == 'none':
            return False
        if not float(self.style.get('opacity', 1.0)):
            return False
        return True

    def get_line_height_uu(self):
        """Returns the specified value of line-height, in user units"""
        style = self.specified_style()
        font_size = style("font-size") # already in uu
        line_height = style("line-height")
        parsed = parse_unit(line_height)
        if parsed is None:
            return font_size * 1.2
        if parsed[1] == "%":
            return font_size * parsed[0] * 0.01
        return self.unittouu(line_height)
