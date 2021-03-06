/**
 * Tests for the EvaluateTeamsCtrl controller.
 */


describe("EvaluateTeamsCtrl controller", function() {
    var httpBackend, window, evaluateTeamsCtrl;

    beforeEach(module('auvsiSuasApp'));

    beforeEach(inject(function($httpBackend, $controller, Backend) {
        httpBackend = $httpBackend;
        window = {
            expectUrl: null,
            open: function(url, target) {
                expect(url).toEqual(this.expectUrl);
            }
        };

        var teams = [
            {
                id: 1,
                active: false,
                in_air: false
            }
        ];
        httpBackend.whenGET('/api/teams').respond(teams);

        evaluateTeamsCtrl = $controller('EvaluateTeamsCtrl', {
            $window: window,
            Backend: Backend
        });
    }));

    it("Should get evaluate teams", function() {
        httpBackend.flush();
        evaluateTeamsCtrl.selectedTeamId = '1';
        window.expectUrl = '/api/missions/evaluate.zip?team=1';
        evaluateTeamsCtrl.evaluate();
    });
});
