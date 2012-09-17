from pytest import raises
from pyramid.exceptions import Forbidden

from kotti.testing import DummyRequest


class TestAddableTypes:
    def test_view_permitted_yes(self, config, db_session):
        from kotti import DBSession
        from kotti.resources import Node
        from kotti.resources import Document

        config.testing_securitypolicy(permissive=True)
        config.include('kotti.views.edit')
        root = DBSession.query(Node).get(1)
        request = DummyRequest()
        assert Document.type_info.addable(root, request) is True

    def test_view_permitted_no(self, config, db_session):
        from kotti import DBSession
        from kotti.resources import Node
        from kotti.resources import Document

        config.testing_securitypolicy(permissive=False)
        config.include('kotti.views.edit')
        root = DBSession.query(Node).get(1)
        request = DummyRequest()
        assert Document.type_info.addable(root, request) is False


class TestNodePaste:
    def test_get_non_existing_paste_item(self):
        from kotti import DBSession
        from kotti.resources import Node
        from kotti.views.edit import get_paste_item

        root = DBSession.query(Node).get(1)
        request = DummyRequest()
        request.session['kotti.paste'] = (1701, 'copy')
        item = get_paste_item(root, request)
        assert item is None

    def test_paste_non_existing_node(self):
        from kotti import DBSession
        from kotti.resources import Node
        from kotti.views.edit import paste_node

        root = DBSession.query(Node).get(1)
        request = DummyRequest()

        for index, action in enumerate(['copy', 'cut']):
            request.session['kotti.paste'] = (1701, 'copy')
            response = paste_node(root, request)
            assert response.status == '302 Found'
            assert len(request.session['_f_error']) == index + 1

    def test_paste_without_edit_permission(self, config, db_session):
        from kotti import DBSession
        from kotti.resources import Node
        from kotti.views.edit import paste_node

        root = DBSession.query(Node).get(1)
        request = DummyRequest()
        request.params['paste'] = u'on'
        config.testing_securitypolicy(permissive=False)

        # We need to have the 'edit' permission on the original object
        # to be able to cut and paste:
        request.session['kotti.paste'] = (1, 'cut')
        with raises(Forbidden):
            paste_node(root, request)

        # We don't need 'edit' permission if we're just copying:
        request.session['kotti.paste'] = (1, 'copy')
        response = paste_node(root, request)
        assert response.status == '302 Found'


class TestNodeRename:
    def test_rename_to_empty_name(self):
        from kotti import DBSession
        from kotti.resources import Node
        from kotti.resources import Document
        from kotti.views.edit import rename_node

        root = DBSession.query(Node).get(1)
        child = root['child'] = Document(title=u"Child")
        request = DummyRequest()
        request.params['rename'] = u'on'
        request.params['name'] = u''
        request.params['title'] = u'foo'
        rename_node(child, request)
        assert (request.session.pop_flash('error') ==
            [u'Name and title are required.'])


class TestNodeShare:
    def test_roles(self, db_session):
        from kotti.views.users import share_node
        from kotti.resources import get_root
        from kotti.security import SHARING_ROLES

        # The 'share_node' view will return a list of available roles
        # as defined in 'kotti.security.SHARING_ROLES'
        root = get_root()
        request = DummyRequest()
        assert (
            [r.name for r in share_node(root, request)['available_roles']] ==
            SHARING_ROLES)

    def test_search(self, extra_principals):
        from kotti.resources import get_root
        from kotti.security import get_principals
        from kotti.security import set_groups
        from kotti.views.users import share_node

        root = get_root()
        request = DummyRequest()
        P = get_principals()

        # Search for "Bob", which will return both the user and the
        # group, both of which have no roles:
        request.params['search'] = u''
        request.params['query'] = u'Bob'
        entries = share_node(root, request)['entries']
        assert len(entries) == 2
        assert entries[0][0] == P['bob']
        assert entries[0][1] == ([], [])
        assert entries[1][0] == P['group:bobsgroup']
        assert entries[1][1] == ([], [])

        # We make Bob an Editor in this context, and Bob's Group
        # becomes global Admin:
        set_groups(u'bob', root, [u'role:editor'])
        P[u'group:bobsgroup'].groups = [u'role:admin']
        entries = share_node(root, request)['entries']
        assert len(entries) == 2
        assert entries[0][0] == P['bob']
        assert entries[0][1] == ([u'role:editor'], [])
        assert entries[1][0] == P['group:bobsgroup']
        assert entries[1][1] == ([u'role:admin'], [u'role:admin'])

        # A search that doesn't return any items will still include
        # entries with existing local roles:
        request.params['query'] = u'Weeee'
        entries = share_node(root, request)['entries']
        assert len(entries) == 1
        assert entries[0][0] == P[u'bob']
        assert entries[0][1] == ([u'role:editor'], [])
        assert (request.session.pop_flash('info') ==
            [u'No users or groups found.'])

        # It does not, however, include entries that have local group
        # assignments only:
        set_groups(u'frank', root, [u'group:franksgroup'])
        request.params['query'] = u'Weeee'
        entries = share_node(root, request)['entries']
        assert len(entries) == 1
        assert entries[0][0] == P['bob']

    def test_apply(self, extra_principals):
        from kotti.resources import get_root
        from kotti.security import list_groups
        from kotti.security import set_groups
        from kotti.views.users import share_node

        root = get_root()
        request = DummyRequest()

        request.params['apply'] = u''
        share_node(root, request)
        assert (request.session.pop_flash('info') == [u'No changes made.'])
        assert list_groups('bob', root) == []
        set_groups('bob', root, ['role:special'])

        request.params['role::bob::role:owner'] = u'1'
        request.params['role::bob::role:editor'] = u'1'
        request.params['orig-role::bob::role:owner'] = u''
        request.params['orig-role::bob::role:editor'] = u''

        share_node(root, request)
        assert (request.session.pop_flash('success') ==
            [u'Your changes have been saved.'])
        assert (
            set(list_groups('bob', root)) ==
            set(['role:owner', 'role:editor', 'role:special'])
            )

        # We cannot set a role that's not displayed, even if we forged
        # the request:
        request.params['role::bob::role:admin'] = u'1'
        request.params['orig-role::bob::role:admin'] = u''
        with raises(Forbidden):
            share_node(root, request)
        assert (
            set(list_groups('bob', root)) ==
            set(['role:owner', 'role:editor', 'role:special'])
            )
